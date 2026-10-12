import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import (
    require_GET,
    require_POST,
    require_http_methods,
)

from apps.orders.models import OrderStatus
from apps.orders.selectors import order_for_buyer_or_404
from apps.orders.services import expire_order_reservation

from .gateways.base import (
    PaymentGatewayConfigurationError,
    PaymentGatewayError,
    PaymentGatewayTemporaryError,
)
from .forms import PaymentPayerForm
from .models import (
    PaymentMethod,
    PaymentStatus,
)
from .services import initiate_order_payment
from .webhook_services import (
    WebhookPayloadConflict,
    WebhookProcessingError,
    WebhookProviderMismatch,
    process_mercado_pago_order_webhook,
)
from .webhooks import (
    WebhookSignatureError,
    validate_mercado_pago_signature,
)

TERMINAL_PAYMENT_STATES = {
    "approved",
    "refunded",
    "charged_back",
    "canceled",
    "expired",
    "rejected",
    "error",
}


def _service_error_messages(error):
    if hasattr(error, "message_dict"):
        return [
            message
            for message_list in error.message_dict.values()
            for message in message_list
        ]

    if hasattr(error, "messages"):
        return list(error.messages)

    return [str(error)]


@login_required
@require_http_methods(["GET", "POST"])
def payer_details(request, public_code):
    """Coleta o CPF do pagador antes de criar a cobrança PIX."""

    order = order_for_buyer_or_404(
        buyer=request.user,
        public_code=public_code,
    )

    if not settings.MARKETPLACE_PAYMENTS_ENABLED:
        return redirect(
            "registrations:participants",
            public_code=order.public_code,
        )

    if order.is_expirable:
        expiration_result = expire_order_reservation(
            order_id=order.id,
        )
        messages.error(
            request,
            "O prazo da reserva terminou. Inicie uma nova inscrição.",
        )
        return redirect(
            "orders:checkout-detail",
            public_code=expiration_result.order.public_code,
        )

    if order.status == OrderStatus.PAID:
        return redirect(
            "payments:detail",
            public_code=order.public_code,
        )

    if order.status != OrderStatus.AWAITING_PAYMENT:
        messages.error(
            request,
            "Este pedido não está disponível para pagamento.",
        )
        return redirect(
            "orders:checkout-detail",
            public_code=order.public_code,
        )

    open_payment = order.payments.open().first()

    if (
        open_payment is not None
        and open_payment.provider_order_id
        and open_payment.pix_copy_paste
    ):
        return redirect(
            "payments:detail",
            public_code=order.public_code,
        )

    form = PaymentPayerForm(
        request.POST or None,
        initial={
            "full_name": " ".join(
                part
                for part in (
                    request.user.first_name,
                    request.user.last_name,
                )
                if part
            ),
        },
    )

    if request.method == "POST" and form.is_valid():
        try:
            result = initiate_order_payment(
                order_id=order.id,
                buyer=request.user,
                payer_data=form.payer_payload(),
            )
        except (ValidationError, PaymentGatewayError) as error:
            for error_message in _service_error_messages(error):
                form.add_error(None, error_message)
        else:
            if result.is_free:
                messages.success(
                    request,
                    "Inscrição gratuita confirmada.",
                )
            else:
                messages.success(
                    request,
                    "Cobrança PIX criada com segurança.",
                )

            return redirect(
                "payments:detail",
                public_code=order.public_code,
            )

    return render(
        request,
        "payments/payer_details.html",
        {
            "order": order,
            "form": form,
            "buyer_email": request.user.email,
        },
    )


def _payment_ui_state(*, order, payment):
    """
    Traduz os estados internos para os estados exibidos
    no frontend sem colocar regras de negócio no template.
    """
    if (
        order.status == OrderStatus.CHARGED_BACK
        or payment.status == PaymentStatus.CHARGED_BACK
    ):
        return "charged_back"

    if (
        order.status == OrderStatus.REFUNDED
        or payment.status == PaymentStatus.REFUNDED
    ):
        return "refunded"

    if (
        order.status == OrderStatus.PAID
        and payment.status == PaymentStatus.APPROVED
    ):
        return "approved"

    if (
        order.status == OrderStatus.CANCELED
        or payment.status == PaymentStatus.CANCELED
    ):
        return "canceled"

    if (
        order.status == OrderStatus.EXPIRED
        or payment.status == PaymentStatus.EXPIRED
        or payment.has_expired
    ):
        return "expired"

    if payment.status == PaymentStatus.REJECTED:
        return "rejected"

    if payment.status == PaymentStatus.ERROR:
        return "error"

    if payment.status in {
        PaymentStatus.CREATED,
        PaymentStatus.PENDING,
    }:
        return "pending"

    return "unavailable"


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
            (
                "payments:payer-details"
                if settings.MARKETPLACE_PAYMENTS_ENABLED
                else "registrations:participants"
            ),
            public_code=order.public_code,
        )

    if order.is_expirable:
        expiration_result = expire_order_reservation(
            order_id=order.id,
        )

        order = expiration_result.order
        payment.refresh_from_db()

    # Deve ficar fora do bloco de expiração porque todos os
    # pagamentos precisam possuir um estado visual.
    ui_state = _payment_ui_state(
        order=order,
        payment=payment,
    )

    is_approved = ui_state == "approved"
    is_refunded = ui_state == "refunded"
    is_charged_back = ui_state == "charged_back"
    is_canceled = ui_state == "canceled"
    is_expired = ui_state == "expired"
    is_rejected = ui_state == "rejected"
    has_payment_error = ui_state == "error"

    is_free = (
        payment.method == PaymentMethod.FREE
    )

    show_pix = (
        ui_state == "pending"
        and payment.method == PaymentMethod.PIX
        and bool(payment.pix_copy_paste)
        and bool(payment.pix_qr_code_base64)
    )

    context = {
        "order": order,
        "order_items": (
            order.items
            .select_related("ticket_type")
            .all()
        ),
        "payment": payment,
        "ui_state": ui_state,
        "is_approved": is_approved,
        "is_refunded": is_refunded,
        "is_charged_back": is_charged_back,
        "is_canceled": is_canceled,
        "is_expired": is_expired,
        "is_rejected": is_rejected,
        "has_payment_error": has_payment_error,
        "is_free": is_free,
        "show_pix": show_pix,
        "qr_code_data_uri": (
            _qr_code_data_uri(
                payment.pix_qr_code_base64
            )
        ),
        "payment_status_url": reverse(
            "payments:status",
            kwargs={
                "public_code": order.public_code,
            },
        ),
    }

    return render(
        request,
        "payments/payment_detail.html",
        context,
    )


@login_required
@require_GET
def payment_status_snapshot(request, public_code):
    """
    Retorna somente o estado necessário para a página de pagamento.

    Não consulta o Mercado Pago e não expõe dados financeiros,
    pessoais ou credenciais.
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
        return JsonResponse(
            {"status": "not_found"},
            status=404,
        )

    if order.is_expirable:
        expiration_result = expire_order_reservation(
            order_id=order.id,
        )

        order = expiration_result.order
        payment.refresh_from_db()

    state = _payment_ui_state(
        order=order,
        payment=payment,
    )

    updated_at = max(
        order.updated_at,
        payment.updated_at,
    )

    return JsonResponse(
        {
            "state": state,
            "terminal": (
                state in TERMINAL_PAYMENT_STATES
            ),
            "updated_at": updated_at.isoformat(),
            "detail_url": reverse(
                "payments:detail",
                kwargs={
                    "public_code": order.public_code,
                },
            ),
        }
    )


@csrf_exempt
@require_POST
def mercado_pago_order_webhook(request):
    """
    Endpoint utilizado exclusivamente pelo Mercado Pago.

    A proteção CSRF não se aplica porque o Mercado Pago não possui
    uma sessão do Django. A autenticação é feita com HMAC-SHA256.
    """
    secret = settings.MERCADO_PAGO_WEBHOOK_SECRET

    if not secret:
        return JsonResponse(
            {"status": "unavailable"},
            status=503,
        )

    signature_header = request.headers.get(
        "x-signature",
        "",
    )

    request_id = request.headers.get(
        "x-request-id",
        "",
    )

    resource_id = request.GET.get(
        "data.id",
        "",
    ).strip()

    event_type = request.GET.get(
        "type",
        "",
    ).strip()

    try:
        validate_mercado_pago_signature(
            secret=secret,
            signature_header=signature_header,
            request_id=request_id,
            data_id=resource_id,
        )

    except WebhookSignatureError:
        return JsonResponse(
            {"status": "unauthorized"},
            status=401,
        )

    raw_body = request.body

    if (
        len(raw_body)
        > settings.PAYMENT_WEBHOOK_MAX_BODY_BYTES
    ):
        return JsonResponse(
            {"status": "payload_too_large"},
            status=413,
        )

    try:
        payload = json.loads(
            raw_body.decode("utf-8")
        )

    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return JsonResponse(
            {"status": "invalid_payload"},
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {"status": "invalid_payload"},
            status=400,
        )

    payload_data = payload.get("data")

    if not isinstance(payload_data, dict):
        return JsonResponse(
            {"status": "invalid_payload"},
            status=400,
        )

    body_resource_id = str(
        payload_data.get("id") or ""
    ).strip()

    body_event_type = str(
        payload.get("type") or ""
    ).strip()

    if (
        resource_id != body_resource_id
        or event_type not in {"payment", "order"}
        or body_event_type != event_type
    ):
        return JsonResponse(
            {"status": "resource_mismatch"},
            status=400,
        )

    try:
        result = process_mercado_pago_order_webhook(
            payload=payload,
            raw_body=raw_body,
            resource_id=resource_id,
            request_id=request_id,
        )

    except WebhookPayloadConflict:
        return JsonResponse(
            {"status": "conflict"},
            status=409,
        )

    except WebhookProviderMismatch:
        return JsonResponse(
            {"status": "provider_mismatch"},
            status=409,
        )

    except PaymentGatewayTemporaryError:
        return JsonResponse(
            {"status": "provider_unavailable"},
            status=503,
        )

    except PaymentGatewayConfigurationError:
        return JsonResponse(
            {"status": "configuration_error"},
            status=503,
        )

    except PaymentGatewayError:
        return JsonResponse(
            {"status": "provider_error"},
            status=502,
        )

    except WebhookProcessingError:
        return JsonResponse(
            {"status": "invalid_notification"},
            status=400,
        )

    return JsonResponse(
        {
            "status": "accepted",
            "duplicate": result.duplicate,
            "ignored": result.ignored,
        },
        status=200,
    )
