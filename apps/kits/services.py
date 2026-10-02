from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404

from apps.events.models import Event, EventStatus, TicketType

from .models import EventKit, KitOption, TicketTypeKit


KIT_FIELDS = (
    "name",
    "description",
    "is_required",
    "is_active",
)

OPTION_FIELDS = (
    "name",
    "stock_quantity",
    "is_active",
)


def _locked_draft_event(*, organization, event_id):
    """
    Bloqueia o evento no PostgreSQL e permite alterações somente
    enquanto ele estiver em rascunho.
    """

    return get_object_or_404(
        Event.objects.select_for_update(),
        id=event_id,
        organization=organization,
        status=EventStatus.DRAFT,
    )


def _locked_ticket_types_for_event(
    *,
    event,
    requested_ticket_types,
):
    requested_ids = {
        ticket_type.pk
        for ticket_type in requested_ticket_types
        if ticket_type.pk is not None
    }

    if not requested_ids:
        raise ValidationError(
            {
                "ticket_types": (
                    "Selecione pelo menos um tipo de ingresso."
                )
            }
        )

    ticket_types = list(
        TicketType.objects.select_for_update()
        .filter(
            event=event,
            id__in=requested_ids,
        )
        .order_by("name", "id")
    )

    if len(ticket_types) != len(requested_ids):
        raise ValidationError(
            {
                "ticket_types": (
                    "Um dos tipos de ingresso selecionados não "
                    "pertence a este evento."
                )
            }
        )

    return ticket_types


def _replace_ticket_type_links(*, kit, ticket_types):
    """
    Sincroniza os tipos de ingresso vinculados ao kit.

    Esta operação só é chamada depois que o evento foi bloqueado e
    confirmado como rascunho.
    """

    existing_links = list(
        TicketTypeKit.objects.select_for_update().filter(kit=kit)
    )

    existing_by_ticket_type = {
        link.ticket_type_id: link
        for link in existing_links
    }

    requested_ids = {
        ticket_type.id
        for ticket_type in ticket_types
    }

    links_to_remove = [
        link.id
        for ticket_type_id, link in existing_by_ticket_type.items()
        if ticket_type_id not in requested_ids
    ]

    if links_to_remove:
        TicketTypeKit.objects.filter(
            id__in=links_to_remove
        ).delete()

    links_to_create = []

    for ticket_type in ticket_types:
        if ticket_type.id in existing_by_ticket_type:
            continue

        link = TicketTypeKit(
            kit=kit,
            ticket_type=ticket_type,
        )
        link.full_clean()
        links_to_create.append(link)

    if links_to_create:
        TicketTypeKit.objects.bulk_create(links_to_create)


@transaction.atomic
def create_event_kit(
    *,
    organization,
    event_id,
    cleaned_data,
):
    """
    Cria um kit e seus vínculos dentro de uma única transação.
    """

    event = _locked_draft_event(
        organization=organization,
        event_id=event_id,
    )

    ticket_types = _locked_ticket_types_for_event(
        event=event,
        requested_ticket_types=cleaned_data["ticket_types"],
    )

    kit = EventKit(
        event=event,
        **{
            field: cleaned_data[field]
            for field in KIT_FIELDS
        },
    )
    kit.full_clean()
    kit.save()

    _replace_ticket_type_links(
        kit=kit,
        ticket_types=ticket_types,
    )

    return kit


@transaction.atomic
def update_event_kit(
    *,
    organization,
    event_id,
    kit_id,
    cleaned_data,
):
    """
    Atualiza o kit somente se o evento for da organização ativa e
    continuar em rascunho.
    """

    event = _locked_draft_event(
        organization=organization,
        event_id=event_id,
    )

    kit = get_object_or_404(
        EventKit.objects.select_for_update(),
        id=kit_id,
        event=event,
    )

    ticket_types = _locked_ticket_types_for_event(
        event=event,
        requested_ticket_types=cleaned_data["ticket_types"],
    )

    for field in KIT_FIELDS:
        setattr(kit, field, cleaned_data[field])

    kit.full_clean()
    kit.save(update_fields=(*KIT_FIELDS, "updated_at"))

    _replace_ticket_type_links(
        kit=kit,
        ticket_types=ticket_types,
    )

    return kit


@transaction.atomic
def create_kit_option(
    *,
    organization,
    event_id,
    kit_id,
    cleaned_data,
):
    """
    Cria uma opção de kit mantendo o isolamento por organização.
    """

    event = _locked_draft_event(
        organization=organization,
        event_id=event_id,
    )

    kit = get_object_or_404(
        EventKit.objects.select_for_update(),
        id=kit_id,
        event=event,
    )

    option = KitOption(
        kit=kit,
        **{
            field: cleaned_data[field]
            for field in OPTION_FIELDS
        },
    )
    option.full_clean()
    option.save()

    return option


@transaction.atomic
def update_kit_option(
    *,
    organization,
    event_id,
    kit_id,
    option_id,
    cleaned_data,
):
    """
    Atualiza a opção somente dentro do evento e da organização
    informados.
    """

    event = _locked_draft_event(
        organization=organization,
        event_id=event_id,
    )

    kit = get_object_or_404(
        EventKit.objects.select_for_update(),
        id=kit_id,
        event=event,
    )

    option = get_object_or_404(
        KitOption.objects.select_for_update(),
        id=option_id,
        kit=kit,
    )

    for field in OPTION_FIELDS:
        setattr(option, field, cleaned_data[field])

    option.full_clean()
    option.save(update_fields=(*OPTION_FIELDS, "updated_at"))

    return option