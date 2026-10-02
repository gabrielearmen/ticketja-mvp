from dataclasses import dataclass

from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.events.models import Event, TicketType

from apps.orders.models import OrderStatus

from .models import (
    EventKit,
    KitOption,
    RegistrationKitSelection,
)


@dataclass(frozen=True, slots=True)
class KitOptionAvailability:
    option: KitOption
    reserved_quantity: int
    available_quantity: int


def kit_management_event_or_404(*, organization, event_id):
    """
    Retorna o evento somente quando ele pertence à organização ativa.
    """

    return get_object_or_404(
        Event.objects.select_related("organization"),
        id=event_id,
        organization=organization,
    )


def kits_for_event(*, event):
    """
    Lista os kits do evento com opções e tipos de ingresso carregados
    antecipadamente, evitando consultas repetidas ao banco.
    """

    option_queryset = KitOption.objects.order_by("name", "id")
    ticket_type_queryset = TicketType.objects.order_by("name", "id")

    return (
        EventKit.objects.filter(event=event)
        .prefetch_related(
            Prefetch(
                "options",
                queryset=option_queryset,
            ),
            Prefetch(
                "ticket_types",
                queryset=ticket_type_queryset,
            ),
        )
        .order_by("name", "id")
    )


def kit_for_event_or_404(
    *,
    organization,
    event_id,
    kit_id,
):
    """
    Impede que uma organização consulte um kit pertencente a outra.
    """

    return get_object_or_404(
        EventKit.objects.select_related(
            "event",
            "event__organization",
        ).prefetch_related(
            "ticket_types",
            "options",
        ),
        id=kit_id,
        event_id=event_id,
        event__organization=organization,
    )


def option_for_kit_or_404(
    *,
    organization,
    event_id,
    kit_id,
    option_id,
):
    """
    Localiza uma opção validando toda a cadeia:
    organização -> evento -> kit -> opção.
    """

    return get_object_or_404(
        KitOption.objects.select_related(
            "kit",
            "kit__event",
            "kit__event__organization",
        ),
        id=option_id,
        kit_id=kit_id,
        kit__event_id=event_id,
        kit__event__organization=organization,
    )

def option_availabilities_for_kit(
    *,
    kit,
    at=None,
):
    """
    Calcula o estoque realmente ocupado.

    Ocupam estoque:
    - pedidos pagos;
    - reservas aguardando pagamento ainda válidas.

    Não ocupam estoque:
    - reservas expiradas;
    - pedidos cancelados;
    - pedidos reembolsados;
    - escolhas removidas.
    """

    reference_time = at or timezone.now()

    holding_inventory_filter = (
        Q(
            registration__order_item__order__status=(
                OrderStatus.PAID
            )
        )
        | Q(
            registration__order_item__order__status=(
                OrderStatus.AWAITING_PAYMENT
            ),
            registration__order_item__order__reservation_expires_at__gt=(
                reference_time
            ),
        )
    )

    reserved_rows = (
        RegistrationKitSelection.objects
        .filter(kit=kit)
        .filter(holding_inventory_filter)
        .values("option_id")
        .annotate(total=Count("id"))
    )

    reserved_by_option = {
        row["option_id"]: row["total"]
        for row in reserved_rows
    }

    return [
        KitOptionAvailability(
            option=option,
            reserved_quantity=(
                reserved_by_option.get(option.id, 0)
            ),
            available_quantity=max(
                option.stock_quantity
                - reserved_by_option.get(option.id, 0),
                0,
            ),
        )
        for option in kit.options.all()
    ]

@dataclass(frozen=True, slots=True)
class ParticipantKitAvailability:
    kit: EventKit
    option_rows: tuple[KitOptionAvailability, ...]

def participant_kit_catalog_for_ticket_types(
    *,
    ticket_type_ids,
    at=None,
):
    """
    Monta o catálogo de kits aplicáveis aos tipos de ingresso.

    O catálogo é preparado uma vez por requisição e compartilhado
    entre os formulários dos participantes, evitando consultas
    repetidas desnecessariamente.
    """

    normalized_ticket_type_ids = {
        ticket_type_id
        for ticket_type_id in ticket_type_ids
        if ticket_type_id is not None
    }

    if not normalized_ticket_type_ids:
        return {}

    reference_time = at or timezone.now()

    applicable_ticket_types = (
        TicketType.objects
        .filter(id__in=normalized_ticket_type_ids)
        .only("id")
        .order_by("id")
    )

    kits = (
        EventKit.objects
        .filter(
            is_active=True,
            ticket_types__id__in=(
                normalized_ticket_type_ids
            ),
        )
        .distinct()
        .prefetch_related(
            Prefetch(
                "options",
                queryset=(
                    KitOption.objects
                    .order_by("name", "id")
                ),
            ),
            Prefetch(
                "ticket_types",
                queryset=applicable_ticket_types,
                to_attr="participant_ticket_types",
            ),
        )
        .order_by("name", "id")
    )

    catalog = {
        ticket_type_id: []
        for ticket_type_id in normalized_ticket_type_ids
    }

    for kit in kits:
        option_rows = tuple(
            availability
            for availability
            in option_availabilities_for_kit(
                kit=kit,
                at=reference_time,
            )
            if availability.option.is_active
        )

        kit_availability = ParticipantKitAvailability(
            kit=kit,
            option_rows=option_rows,
        )

        for ticket_type in (
            kit.participant_ticket_types
        ):
            catalog[ticket_type.id].append(
                kit_availability
            )

    return {
        ticket_type_id: tuple(kit_entries)
        for ticket_type_id, kit_entries
        in catalog.items()
    }