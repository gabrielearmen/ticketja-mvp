from django.urls import path

from .views import participant_details


app_name = "registrations"


urlpatterns = [
    path(
        "checkout/<str:public_code>/participantes/",
        participant_details,
        name="participants",
    ),
]