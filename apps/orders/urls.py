from django.urls import path

from .views import (
    checkout_detail,
    start_checkout,
)


app_name = "orders"


urlpatterns = [
    path(
        "eventos/<uuid:event_id>/inscricao/",
        start_checkout,
        name="start",
    ),
    path(
        "checkout/<str:public_code>/",
        checkout_detail,
        name="checkout-detail",
    ),
]