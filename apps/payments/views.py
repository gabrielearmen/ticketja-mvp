from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from apps.orders.models import OrderStatus
from apps.orders.selectors import order_for_buyer_or_404
from apps.orders.services import expire_order_reservation

from .models import (
    PaymentMethod,
    PaymentStatus,
)


def _qr_code_data_uri(raw_base64):
    normalized = (raw_base64 or "").strip()

    if not normalized:
        return ""

    if normalized.startswith("data:image/"):
        return normalized

    return f"data:image/png;base64,{normalized}"


@login_required
@require_GET
def payment_detail(request, public_code):
    """
    Exibe somente uma cobrança já criada.

    Esta view não chama o provedor e não cria pagamentos.
    Portanto, atualizar a página é seguro e idempotente.
    """
    order = order_for_buyer_or_404(
        buyer=request.user,
        public_code=public_code,
    )

    payment = (
        order.payments
        .order_by(
            "-attempt_number",
            "-created_at",
        )
        .first()
    )

    if payment is None:
        messages.error(
            request,
            (
                "Inicie o pagamento após concluir os "
                "participantes."
            ),
        )

        return redirect(
            "registrations:participants",
            public_code=order.public_code,
        )

    if order.is_expirable:
        expiration_result = expire_order_reservation(
            order_id=order.id,
        )
        order = expiration_result.order
        payment.refresh_from_db()

    is_approved = (
        order.status == OrderStatus.PAID
        and payment.status == PaymentStatus.APPROVED
    )

    is_free = (
        payment.method == PaymentMethod.FREE
    )

    is_expired = (
        order.status == OrderStatus.EXPIRED
        or payment.has_expired
    )

    show_pix = (
        payment.method == PaymentMethod.PIX
        and payment.status == PaymentStatus.PENDING
        and not is_expired
        and bool(payment.pix_copy_paste)
        and bool(payment.pix_qr_code_base64)
    )

    context = {
        "order": order,
        "order_items": order.items.all(),
        "payment": payment,
        "is_approved": is_approved,
        "is_free": is_free,
        "is_expired": is_expired,
        "show_pix": show_pix,
        "qr_code_data_uri": (
            _qr_code_data_uri(
                payment.pix_qr_code_base64
            )
        ),
    }

    return render(
        request,
        "payments/payment_detail.html",
        context,
    )