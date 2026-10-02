from django.urls import path

from .views import payment_detail


app_name = "payments"


urlpatterns = [
    path(
        "checkout/<str:public_code>/pagamento/",
        payment_detail,
        name="detail",
    ),
]