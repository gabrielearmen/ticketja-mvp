from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import (
    Event,
    EventStatus,
    TicketLot,
    TicketType,
)

from .rules import commercial_configuration_errors

EVENT_FORM_FIELDS = (
    "title",
    "summary",
    "sport_category",
    "event_datetime",
    "city",
    "state",
    "address",
    "capacity",
    "cover_image",
)


def _event_data_from(cleaned_data):
    """
    Aceita somente os campos definidos pelo servidor.

    Mesmo que dados adicionais sejam enviados pelo navegador,
    eles não serão utilizados.
    """
    return {
        field_name: cleaned_data[field_name]
        for field_name in EVENT_FORM_FIELDS
    }


@transaction.atomic
def create_draft_event(
    *,
    organization,
    cleaned_data,
):
    event = Event(
        organization=organization,
        status=EventStatus.DRAFT,
        **_event_data_from(cleaned_data),
    )

    event.full_clean()
    event.save()

    return event


@transaction.atomic
def update_draft_event(
    *,
    organization,
    event_id,
    cleaned_data,
):
    """
    Bloqueia a linha no PostgreSQL durante a atualização.

    Isso impede que uma publicação e uma edição concorrentes
    modifiquem o mesmo evento simultaneamente.
    """
    event = get_object_or_404(
        Event.objects.select_for_update(),
        id=event_id,
        organization=organization,
        status=EventStatus.DRAFT,
    )

    for field_name, value in _event_data_from(
        cleaned_data
    ).items():
        setattr(event, field_name, value)

    event.full_clean()

    event.save(
        update_fields=(
            *EVENT_FORM_FIELDS,
            "updated_at",
        )
    )

    return event


@transaction.atomic
def publish_event(
    *,
    organization,
    event_id,
):
    event = get_object_or_404(
        Event.objects.select_for_update(),
        id=event_id,
        organization=organization,
    )

    # As alterações comerciais também bloqueiam o evento.
    # O mesmo bloqueio serializa publicação e edição.
    list(
        TicketType.objects
        .select_for_update()
        .filter(event=event)
    )

    list(
        TicketLot.objects
        .select_for_update()
        .filter(ticket_type__event=event)
    )

    configuration_errors = (
        commercial_configuration_errors(event)
    )

    if configuration_errors:
        raise ValidationError(configuration_errors)

    event.publish()

    event.save(
        update_fields=(
            "status",
            "updated_at",
        )
    )

    return event

@transaction.atomic
def cancel_event(
    *,
    organization,
    event_id,
):
    event = get_object_or_404(
        Event.objects.select_for_update(),
        id=event_id,
        organization=organization,
    )

    event.cancel()

    event.save(
        update_fields=(
            "status",
            "updated_at",
        )
    )

    return event


TICKET_TYPE_FORM_FIELDS = (
    "name",
    "description",
    "capacity",
    "is_active",
)


def _ticket_type_data_from(cleaned_data):
    return {
        field_name: cleaned_data[field_name]
        for field_name in TICKET_TYPE_FORM_FIELDS
    }


def _validate_ticket_type_capacity(
    *,
    event,
    capacity,
    is_active,
    ignored_ticket_type_id=None,
):
    """
    Impede que a soma das categorias ativas ultrapasse
    a capacidade total do evento.

    O evento estará bloqueado com select_for_update quando esta
    função for chamada, evitando duas gravações concorrentes.
    """
    ticket_types = event.ticket_types.filter(
        is_active=True
    )

    if ignored_ticket_type_id is not None:
        ticket_types = ticket_types.exclude(
            id=ignored_ticket_type_id
        )

    allocated_capacity = (
        ticket_types.aggregate(total=Sum("capacity"))["total"]
        or 0
    )

    requested_capacity = capacity if is_active else 0

    if allocated_capacity + requested_capacity > event.capacity:
        available_capacity = max(
            event.capacity - allocated_capacity,
            0,
        )

        raise ValidationError(
            {
                "capacity": (
                    "A capacidade informada ultrapassa o limite "
                    f"do evento. Restam {available_capacity} vagas "
                    "para categorias ativas."
                )
            }
        )


@transaction.atomic
def create_ticket_type(
    *,
    organization,
    event_id,
    cleaned_data,
):
    event = get_object_or_404(
        Event.objects.select_for_update(),
        id=event_id,
        organization=organization,
        status=EventStatus.DRAFT,
    )

    ticket_type_data = _ticket_type_data_from(
        cleaned_data
    )

    _validate_ticket_type_capacity(
        event=event,
        capacity=ticket_type_data["capacity"],
        is_active=ticket_type_data["is_active"],
    )

    ticket_type = TicketType(
        event=event,
        **ticket_type_data,
    )

    ticket_type.full_clean()
    ticket_type.save()

    return ticket_type


@transaction.atomic
def update_ticket_type(
    *,
    organization,
    event_id,
    ticket_type_id,
    cleaned_data,
):
    event = get_object_or_404(
        Event.objects.select_for_update(),
        id=event_id,
        organization=organization,
        status=EventStatus.DRAFT,
    )

    ticket_type = get_object_or_404(
        TicketType.objects.select_for_update(),
        id=ticket_type_id,
        event=event,
    )

    ticket_type_data = _ticket_type_data_from(
        cleaned_data
    )

    _validate_ticket_type_capacity(
        event=event,
        capacity=ticket_type_data["capacity"],
        is_active=ticket_type_data["is_active"],
        ignored_ticket_type_id=ticket_type.id,
    )

    active_lot_quantity = (
        ticket_type.lots
        .filter(is_active=True)
        .aggregate(total=Sum("quantity"))["total"]
        or 0
    )

    if (
        ticket_type_data["is_active"]
        and ticket_type_data["capacity"]
        < active_lot_quantity
    ):
        raise ValidationError(
            {
                "capacity": (
                    "A capacidade não pode ser menor que a "
                    f"quantidade já distribuída nos lotes ativos "
                    f"({active_lot_quantity})."
                )
            }
        )

    if (
        not ticket_type_data["is_active"]
        and active_lot_quantity > 0
    ):
        raise ValidationError(
            {
                "is_active": (
                    "Desative todos os lotes antes de desativar "
                    "este tipo de ingresso."
                )
            }
        )

    for field_name, value in ticket_type_data.items():
        setattr(ticket_type, field_name, value)

    ticket_type.full_clean()

    ticket_type.save(
        update_fields=(
            *TICKET_TYPE_FORM_FIELDS,
            "updated_at",
        )
    )

    return ticket_type


TICKET_LOT_FORM_FIELDS = (
    "name",
    "price",
    "quantity",
    "sales_start",
    "sales_end",
    "is_active",
)


def _ticket_lot_data_from(cleaned_data):
    return {
        field_name: cleaned_data[field_name]
        for field_name in TICKET_LOT_FORM_FIELDS
    }


def _validate_ticket_lot_limits(
    *,
    ticket_type,
    lot_data,
    ignored_lot_id=None,
    creating=False,
):
    """
    Valida capacidade, período e estado comercial.

    O evento estará bloqueado pelo PostgreSQL durante esta
    validação, evitando gravações concorrentes inconsistentes.
    """
    if creating and not ticket_type.is_active:
        raise ValidationError(
            "Ative o tipo de ingresso antes de criar um lote."
        )

    if lot_data["is_active"] and not ticket_type.is_active:
        raise ValidationError(
            {
                "is_active": (
                    "Um lote ativo precisa pertencer a um "
                    "tipo de ingresso ativo."
                )
            }
        )

    if lot_data["sales_start"] >= lot_data["sales_end"]:
        raise ValidationError(
            {
                "sales_end": (
                    "O encerramento deve ser posterior ao "
                    "início das vendas."
                )
            }
        )

    if (
        lot_data["sales_end"]
        > ticket_type.event.event_datetime
    ):
        raise ValidationError(
            {
                "sales_end": (
                    "As vendas devem terminar antes da "
                    "realização do evento."
                )
            }
        )

    if (
        lot_data["is_active"]
        and lot_data["sales_end"] <= timezone.now()
    ):
        raise ValidationError(
            {
                "sales_end": (
                    "Um lote ativo deve possuir encerramento "
                    "de vendas futuro."
                )
            }
        )

    active_lots = ticket_type.lots.filter(
        is_active=True
    )

    if ignored_lot_id is not None:
        active_lots = active_lots.exclude(
            id=ignored_lot_id
        )

    allocated_quantity = (
        active_lots.aggregate(total=Sum("quantity"))["total"]
        or 0
    )

    requested_quantity = (
        lot_data["quantity"]
        if lot_data["is_active"]
        else 0
    )

    if (
        allocated_quantity + requested_quantity
        > ticket_type.capacity
    ):
        available_quantity = max(
            ticket_type.capacity - allocated_quantity,
            0,
        )

        raise ValidationError(
            {
                "quantity": (
                    "A quantidade ultrapassa a capacidade do "
                    f"tipo de ingresso. Restam "
                    f"{available_quantity} unidades."
                )
            }
        )

    if lot_data["is_active"]:
        overlapping_lots = active_lots.filter(
            sales_start__lt=lot_data["sales_end"],
            sales_end__gt=lot_data["sales_start"],
        )

        if overlapping_lots.exists():
            raise ValidationError(
                {
                    "sales_start": (
                        "O período informado coincide com outro "
                        "lote ativo deste tipo de ingresso."
                    ),
                    "sales_end": (
                        "Ajuste o período para que os lotes "
                        "ativos não se sobreponham."
                    ),
                }
            )


@transaction.atomic
def create_ticket_lot(
    *,
    organization,
    event_id,
    ticket_type_id,
    cleaned_data,
):
    event = get_object_or_404(
        Event.objects.select_for_update(),
        id=event_id,
        organization=organization,
        status=EventStatus.DRAFT,
    )

    ticket_type = get_object_or_404(
        TicketType.objects.select_for_update(),
        id=ticket_type_id,
        event=event,
    )

    lot_data = _ticket_lot_data_from(cleaned_data)

    _validate_ticket_lot_limits(
        ticket_type=ticket_type,
        lot_data=lot_data,
        creating=True,
    )

    ticket_lot = TicketLot(
        ticket_type=ticket_type,
        **lot_data,
    )

    ticket_lot.full_clean()
    ticket_lot.save()

    return ticket_lot


@transaction.atomic
def update_ticket_lot(
    *,
    organization,
    event_id,
    ticket_type_id,
    ticket_lot_id,
    cleaned_data,
):
    event = get_object_or_404(
        Event.objects.select_for_update(),
        id=event_id,
        organization=organization,
        status=EventStatus.DRAFT,
    )

    ticket_type = get_object_or_404(
        TicketType.objects.select_for_update(),
        id=ticket_type_id,
        event=event,
    )

    ticket_lot = get_object_or_404(
        TicketLot.objects.select_for_update(),
        id=ticket_lot_id,
        ticket_type=ticket_type,
    )

    lot_data = _ticket_lot_data_from(cleaned_data)

    _validate_ticket_lot_limits(
        ticket_type=ticket_type,
        lot_data=lot_data,
        ignored_lot_id=ticket_lot.id,
    )

    for field_name, value in lot_data.items():
        setattr(ticket_lot, field_name, value)

    ticket_lot.full_clean()

    ticket_lot.save(
        update_fields=(
            *TICKET_LOT_FORM_FIELDS,
            "updated_at",
        )
    )

    return ticket_lot