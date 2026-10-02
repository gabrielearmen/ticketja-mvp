from django.urls import path

from .views import (
    organizer_kit_configuration,
    organizer_kit_create,
    organizer_kit_option_create,
    organizer_kit_option_update,
    organizer_kit_update,
)


app_name = "kits"


urlpatterns = [
    path(
        "painel/eventos/<uuid:event_id>/kits/",
        organizer_kit_configuration,
        name="configuration",
    ),
    path(
        "painel/eventos/<uuid:event_id>/kits/novo/",
        organizer_kit_create,
        name="create",
    ),
    path(
        (
            "painel/eventos/<uuid:event_id>/kits/"
            "<uuid:kit_id>/editar/"
        ),
        organizer_kit_update,
        name="update",
    ),
    path(
        (
            "painel/eventos/<uuid:event_id>/kits/"
            "<uuid:kit_id>/opcoes/nova/"
        ),
        organizer_kit_option_create,
        name="option-create",
    ),
    path(
        (
            "painel/eventos/<uuid:event_id>/kits/"
            "<uuid:kit_id>/opcoes/"
            "<uuid:option_id>/editar/"
        ),
        organizer_kit_option_update,
        name="option-update",
    ),
]