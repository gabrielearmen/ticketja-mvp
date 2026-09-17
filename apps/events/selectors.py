from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404

from apps.organizations.models import OrganizationStatus

from .models import (
    Event,
    EventStatus,
    TicketLot,
    TicketType,
)


def events_for_organization(organization):
    """
    Retorna somente eventos pertencentes à organização informada.

    Este seletor deve ser usado nas páginas privadas do organizador.
    """
    return (
        Event.objects
        .for_organization(organization)
        .select_related("organization")
        .order_by("-created_at")
    )


def event_for_organization_or_404(
    *,
    organization,
    event_id,
):
    """
    Busca um evento dentro da organização ativa.

    A filtragem pela organização impede que um organizador acesse
    eventos pertencentes a outra empresa alterando o UUID na URL.
    """
    return get_object_or_404(
        Event.objects.for_organization(organization),
        id=event_id,
    )


def editable_event_for_organization_or_404(
    *,
    organization,
    event_id,
):
    """
    Retorna somente eventos em rascunho da organização ativa.
    """
    return get_object_or_404(
        Event.objects.for_organization(organization),
        id=event_id,
        status=EventStatus.DRAFT,
    )


def published_events_for_discovery(
    *,
    search_query="",
    location_query="",
):
    """
    Consulta pública utilizada na Landing Page.

    Nunca retorna:
    - eventos em rascunho;
    - eventos cancelados;
    - eventos já realizados;
    - eventos de organizações suspensas ou não aprovadas.
    """
    events = (
        Event.objects
        .published()
        .upcoming()
        .filter(
            organization__status=OrganizationStatus.APPROVED,
        )
        .select_related("organization")
        .order_by("event_datetime")
    )

    if search_query:
        events = events.filter(
            Q(title__icontains=search_query)
            | Q(summary__icontains=search_query)
            | Q(sport_category__icontains=search_query)
        )

    if location_query:
        events = events.filter(
            Q(city__icontains=location_query)
            | Q(state__iexact=location_query)
        )

    return events


def public_event_for_detail_or_404(*, event_id):
    """
    Retorna um evento publicamente acessível com sua oferta comercial.

    A consulta carrega:
    - organização;
    - tipos de ingresso ativos;
    - lotes ativos de cada tipo.

    O Prefetch evita a execução de uma nova consulta para cada tipo
    de ingresso ou lote exibido na página.
    """
    public_lots = (
        TicketLot.objects
        .filter(is_active=True)
        .order_by(
            "sales_start",
            "price",
            "name",
        )
    )

    public_ticket_types = (
        TicketType.objects
        .filter(is_active=True)
        .prefetch_related(
            Prefetch(
                "lots",
                queryset=public_lots,
                to_attr="public_lots",
            )
        )
        .order_by("name")
    )

    public_events = (
        Event.objects
        .published()
        .upcoming()
        .filter(
            organization__status=OrganizationStatus.APPROVED,
        )
        .select_related("organization")
        .prefetch_related(
            Prefetch(
                "ticket_types",
                queryset=public_ticket_types,
                to_attr="public_ticket_types",
            )
        )
    )

    return get_object_or_404(
        public_events,
        id=event_id,
    )


def ticket_types_for_event(event):
    """
    Carrega tipos e lotes para o painel do organizador.
    """
    return (
        TicketType.objects
        .filter(event=event)
        .prefetch_related("lots")
        .order_by("name")
    )


def ticket_type_for_event_or_404(
    *,
    organization,
    event_id,
    ticket_type_id,
):
    """
    Protege simultaneamente organização, evento e tipo de ingresso.
    """
    return get_object_or_404(
        TicketType.objects.select_related(
            "event",
            "event__organization",
        ),
        id=ticket_type_id,
        event_id=event_id,
        event__organization=organization,
    )


def ticket_lot_for_type_or_404(
    *,
    organization,
    event_id,
    ticket_type_id,
    ticket_lot_id,
):
    """
    Valida toda a cadeia de propriedade do lote.
    """
    return get_object_or_404(
        TicketLot.objects.select_related(
            "ticket_type",
            "ticket_type__event",
            "ticket_type__event__organization",
        ),
        id=ticket_lot_id,
        ticket_type_id=ticket_type_id,
        ticket_type__event_id=event_id,
        ticket_type__event__organization=organization,
    )