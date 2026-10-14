from django.urls import path

from .views import (
    checkout_return,
    mercado_pago_order_webhook,
    payer_details,
    payment_detail,
    payment_status_snapshot,
)


app_name = "payments"


urlpatterns = [
    path(
        "checkout/<str:public_code>/pagador/",
        payer_details,
        name="payer-details",
    ),
    path(
        "checkout/<str:public_code>/pagamento/",
        payment_detail,
        name="detail",
    ),
    path(
        "checkout/<str:public_code>/pagamento/status/",
        payment_status_snapshot,
        name="status",
    ),
    path(
        "checkout/<str:public_code>/pagamento/retorno/<str:outcome>/",
        checkout_return,
        name="return",
    ),
    path(
        "webhooks/mercado-pago/payments/",
        mercado_pago_order_webhook,
        name="mercado-pago-payments-webhook",
    ),
    path(
        "webhooks/mercado-pago/orders/",
        mercado_pago_order_webhook,
        name="mercado-pago-orders-webhook",
    ),
]
