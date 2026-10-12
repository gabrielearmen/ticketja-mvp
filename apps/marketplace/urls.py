from django.urls import path

from .views import (
    mercado_pago_callback,
    mercado_pago_connect,
    payment_account_detail,
)


app_name = "marketplace"


urlpatterns = [
    path(
        "painel/recebimentos/",
        payment_account_detail,
        name="payment-account",
    ),
    path(
        "painel/recebimentos/mercado-pago/conectar/",
        mercado_pago_connect,
        name="mercado-pago-connect",
    ),
    path(
        "painel/recebimentos/mercado-pago/retorno/",
        mercado_pago_callback,
        name="mercado-pago-callback",
    ),
]
