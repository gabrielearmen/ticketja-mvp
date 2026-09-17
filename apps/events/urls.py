from django.urls import path

from .public_views import public_event_detail
from .views import (
    organizer_event_cancel,
    organizer_event_create,
    organizer_event_list,
    organizer_event_publish,
    organizer_event_update,
    organizer_ticket_configuration,
    organizer_ticket_lot_create,
    organizer_ticket_lot_update,
    organizer_ticket_type_create,
    organizer_ticket_type_update,
)


app_name = "events"


urlpatterns = [
    # Área pública
    path(
        "eventos/<uuid:event_id>/",
        public_event_detail,
        name="public-detail",
    ),

    # Painel do organizador
    path(
        "painel/eventos/",
        organizer_event_list,
        name="organizer-list",
    ),
    path(
        "painel/eventos/novo/",
        organizer_event_create,
        name="organizer-create",
    ),
    path(
        "painel/eventos/<uuid:event_id>/editar/",
        organizer_event_update,
        name="organizer-update",
    ),
    path(
        "painel/eventos/<uuid:event_id>/publicar/",
        organizer_event_publish,
        name="organizer-publish",
    ),
    path(
        "painel/eventos/<uuid:event_id>/cancelar/",
        organizer_event_cancel,
        name="organizer-cancel",
    ),
    path(
        "painel/eventos/<uuid:event_id>/ingressos/",
        organizer_ticket_configuration,
        name="ticket-configuration",
    ),
    path(
        "painel/eventos/<uuid:event_id>/ingressos/novo/",
        organizer_ticket_type_create,
        name="ticket-type-create",
    ),
    path(
        (
            "painel/eventos/<uuid:event_id>/"
            "ingressos/<uuid:ticket_type_id>/editar/"
        ),
        organizer_ticket_type_update,
        name="ticket-type-update",
    ),
    path(
        (
            "painel/eventos/<uuid:event_id>/"
            "ingressos/<uuid:ticket_type_id>/lotes/novo/"
        ),
        organizer_ticket_lot_create,
        name="ticket-lot-create",
    ),
    path(
        (
            "painel/eventos/<uuid:event_id>/"
            "ingressos/<uuid:ticket_type_id>/"
            "lotes/<uuid:ticket_lot_id>/editar/"
        ),
        organizer_ticket_lot_update,
        name="ticket-lot-update",
    ),
]