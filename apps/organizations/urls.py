from django.urls import path

from .views import organizer_dashboard


app_name = "organizations"


urlpatterns = [
    path(
        "painel/",
        organizer_dashboard,
        name="dashboard",
    ),
]