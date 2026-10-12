import hashlib
from dataclasses import dataclass

from .confirmation import (
    PaymentConfirmationError,
    reconcile_payment_snapshot,
)

from django.db import transaction
from django.utils import timezone

from .gateways.base import PaymentGatewayError
from .gateways.registry import (
    get_payment_gateway,
    get_payment_gateway_for_payment,
)
from .models import (
    Payment,
    PaymentProvider,
    PaymentWebhookEvent,
    WebhookProcessingStatus,
)


class WebhookProcessingError(Exception):
    """
    Erro base do processamento de Webhooks.
    """


class WebhookPayloadConflict(WebhookProcessingError):
    """
    O mesmo ID de notificação chegou com conteúdo diferente.
    """


class WebhookProviderMismatch(WebhookProcessingError):
    """
    Os dados consultados no provedor não correspondem
    ao pagamento registrado no TicketJá.
    """


@dataclass(frozen=True, slots=True)
class WebhookProcessingResult:
    event_id: object
    duplicate: bool
    ignored: bool
    provider_status: str = ""


@dataclass(frozen=True, slots=True)
class _PreparedWebhook:
    event_id: object
    payment_id: object | None
    duplicate: bool
    ignored: bool
    should_fetch: bool


def _required_text(value, *, field_name, max_length):
    normalized = str(value or "").strip()

    if not normalized:
        raise WebhookProcessingError(
            f"O campo {field_name} não foi informado."
        )

    if len(normalized) > max_length:
        raise WebhookProcessingError(
            f"O campo {field_name} excedeu o limite permitido."
        )

    return normalized


def _payload_hash(raw_body):
    return hashlib.sha256(raw_body).hexdigest()


def _deduplication_key(notification_id):
    source = (
        f"{PaymentProvider.MERCADO_PAGO}:"
        f"{notification_id}"
    )

    return hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


def _prepare_webhook(
    *,
    payload,
    raw_body,
    resource_id,
    request_id,
):
    notification_id = _required_text(
        payload.get("id"),
        field_name="id",
        max_length=255,
    )

    event_type = _required_text(
        payload.get("type"),
        field_name="type",
        max_length=100,
    )

    action = str(
        payload.get("action") or ""
    ).strip()[:100]

    normalized_resource_id = _required_text(
        resource_id,
        field_name="data.id",
        max_length=255,
    )

    normalized_request_id = _required_text(
        request_id,
        field_name="x-request-id",
        max_length=255,
    )

    body_sha256 = _payload_hash(raw_body)

    event, created = (
        PaymentWebhookEvent.objects.get_or_create(
            provider=PaymentProvider.MERCADO_PAGO,
            notification_id=notification_id,
            defaults={
                "event_type": event_type,
                "action": action,
                "resource_id": normalized_resource_id,
                "request_id": normalized_request_id,
                "deduplication_key": (
                    _deduplication_key(
                        notification_id
                    )
                ),
                "payload_sha256": body_sha256,
                "signature_valid": True,
                "processing_status": (
                    WebhookProcessingStatus.RECEIVED
                ),
                "processing_attempts": 1,
            },
        )
    )

    with transaction.atomic():
        event = (
            PaymentWebhookEvent.objects
            .select_for_update()
            .get(id=event.id)
        )

        if not created:
            if event.payload_sha256 != body_sha256:
                raise WebhookPayloadConflict(
                    "A notificação repetida possui "
                    "conteúdo diferente."
                )

            if event.processing_status in {
                WebhookProcessingStatus.PROCESSED,
                WebhookProcessingStatus.IGNORED,
            }:
                return _PreparedWebhook(
                    event_id=event.id,
                    payment_id=event.payment_id,
                    duplicate=True,
                    ignored=(
                        event.processing_status
                        == WebhookProcessingStatus.IGNORED
                    ),
                    should_fetch=False,
                )

            event.processing_attempts += 1
            event.processing_status = (
                WebhookProcessingStatus.RECEIVED
            )
            event.processed_at = None
            event.failure_reason = ""

        payment = (
            Payment.objects
            .select_for_update()
            .filter(
                provider=PaymentProvider.MERCADO_PAGO,
                provider_order_id=normalized_resource_id,
            )
            .first()
        )

        if payment is None:
            event.processing_status = (
                WebhookProcessingStatus.IGNORED
            )
            event.processed_at = timezone.now()
            event.failure_reason = (
                "Recurso não localizado no TicketJá."
            )

            event.save(
                update_fields=(
                    "processing_attempts",
                    "processing_status",
                    "processed_at",
                    "failure_reason",
                    "updated_at",
                )
            )

            return _PreparedWebhook(
                event_id=event.id,
                payment_id=None,
                duplicate=not created,
                ignored=True,
                should_fetch=False,
            )

        event.payment = payment
        event.event_type = event_type
        event.action = action
        event.resource_id = normalized_resource_id
        event.request_id = normalized_request_id
        event.signature_valid = True

        event.save(
            update_fields=(
                "payment",
                "event_type",
                "action",
                "resource_id",
                "request_id",
                "signature_valid",
                "processing_attempts",
                "processing_status",
                "processed_at",
                "failure_reason",
                "updated_at",
            )
        )

        return _PreparedWebhook(
            event_id=event.id,
            payment_id=payment.id,
            duplicate=not created,
            ignored=False,
            should_fetch=True,
        )


@transaction.atomic
def _mark_webhook_failed(*, event_id, reason):
    event = (
        PaymentWebhookEvent.objects
        .select_for_update()
        .get(id=event_id)
    )

    if event.processing_status in {
        WebhookProcessingStatus.PROCESSED,
        WebhookProcessingStatus.IGNORED,
    }:
        return

    event.processing_status = (
        WebhookProcessingStatus.FAILED
    )
    event.failure_reason = str(reason)[:500]
    event.processed_at = timezone.now()

    event.save(
        update_fields=(
            "processing_status",
            "failure_reason",
            "processed_at",
            "updated_at",
        )
    )

@transaction.atomic
def _save_provider_snapshot(
    *,
    event_id,
    snapshot,
):
    event = (
        PaymentWebhookEvent.objects
        .select_for_update()
        .get(id=event_id)
    )

    if event.processing_status == (
        WebhookProcessingStatus.PROCESSED
    ):
        return WebhookProcessingResult(
            event_id=event.id,
            duplicate=True,
            ignored=False,
            provider_status="",
        )

    if event.payment_id is None:
        raise WebhookProviderMismatch(
            "A notificação não está vinculada "
            "a um pagamento."
        )

    try:
        reconciliation = reconcile_payment_snapshot(
            payment_id=event.payment_id,
            snapshot=snapshot,
        )

    except PaymentConfirmationError as error:
        raise WebhookProviderMismatch(
            str(error)
        ) from error

    event.processing_status = (
        WebhookProcessingStatus.PROCESSED
    )
    event.failure_reason = ""
    event.processed_at = timezone.now()

    event.save(
        update_fields=(
            "processing_status",
            "failure_reason",
            "processed_at",
            "updated_at",
        )
    )

    return WebhookProcessingResult(
        event_id=event.id,
        duplicate=(
            reconciliation.already_finalized
        ),
        ignored=False,
        provider_status=snapshot.provider_status,
    )


def process_mercado_pago_order_webhook(
    *,
    payload,
    raw_body,
    resource_id,
    request_id,
    gateway=None,
):
    """
    Registra a notificação, evita reprocessamentos e consulta
    a ordem diretamente no Mercado Pago.

    O status recebido no corpo do webhook nunca é considerado
    prova de pagamento.
    """
    prepared = _prepare_webhook(
        payload=payload,
        raw_body=raw_body,
        resource_id=resource_id,
        request_id=request_id,
    )

    if not prepared.should_fetch:
        return WebhookProcessingResult(
            event_id=prepared.event_id,
            duplicate=prepared.duplicate,
            ignored=prepared.ignored,
        )

    selected_gateway = gateway

    if selected_gateway is None:
        payment = (
            Payment.objects
            .select_related("order__organization")
            .get(id=prepared.payment_id)
        )
        selected_gateway = get_payment_gateway_for_payment(
            payment
        )

    try:
        snapshot = selected_gateway.fetch_payment(
            resource_id
        )

        return _save_provider_snapshot(
            event_id=prepared.event_id,
            snapshot=snapshot,
        )

    except PaymentGatewayError as error:
        _mark_webhook_failed(
            event_id=prepared.event_id,
            reason="Falha ao consultar o provedor.",
        )
        raise

    except WebhookProviderMismatch as error:
        _mark_webhook_failed(
            event_id=prepared.event_id,
            reason=error,
        )
        raise
