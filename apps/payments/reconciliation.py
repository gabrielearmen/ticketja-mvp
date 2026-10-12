from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from .confirmation import (
    PaymentConfirmationError,
    reconcile_payment_snapshot,
)
from .gateways.base import PaymentGatewayError
from .gateways.registry import get_payment_gateway_for_payment
from .models import Payment, PaymentProvider, PaymentStatus


@dataclass(frozen=True, slots=True)
class PaymentReconciliationBatchResult:
    selected: int
    reconciled: int
    failed: int


def _record_attempt(*, payment_id, at, error_message=""):
    Payment.objects.filter(id=payment_id).update(
        reconciliation_attempts=F("reconciliation_attempts") + 1,
        last_reconciled_at=at,
        last_reconciliation_error=str(error_message)[:500],
    )


def reconciliation_candidates(*, at=None, limit=100):
    """Seleciona cobranças que ainda podem mudar no provedor."""

    reference_time = at or timezone.now()
    open_interval = timedelta(
        minutes=settings.PAYMENT_RECONCILIATION_MIN_INTERVAL_MINUTES
    )
    settled_interval = timedelta(
        hours=settings.PAYMENT_SETTLED_RECONCILIATION_INTERVAL_HOURS
    )
    lookback = timedelta(
        days=settings.PAYMENT_RECONCILIATION_LOOKBACK_DAYS
    )

    open_statuses = (
        PaymentStatus.CREATED,
        PaymentStatus.PENDING,
    )
    settled_statuses = (
        PaymentStatus.APPROVED,
        PaymentStatus.REJECTED,
        PaymentStatus.CANCELED,
        PaymentStatus.EXPIRED,
    )

    open_due = (
        Q(status__in=open_statuses)
        & (
            Q(last_reconciled_at__isnull=True)
            | Q(
                last_reconciled_at__lte=(
                    reference_time - open_interval
                )
            )
        )
    )
    settled_due = (
        Q(status__in=settled_statuses)
        & (
            Q(last_reconciled_at__isnull=True)
            | Q(
                last_reconciled_at__lte=(
                    reference_time - settled_interval
                )
            )
        )
    )

    return list(
        Payment.objects
        .filter(
            provider=PaymentProvider.MERCADO_PAGO,
            created_at__gte=reference_time - lookback,
        )
        .exclude(provider_order_id="")
        .filter(open_due | settled_due)
        .select_related("order__organization")
        .order_by("last_reconciled_at", "created_at")[:limit]
    )


def reconcile_provider_payments(
    *,
    at=None,
    limit=100,
    gateway_getter=None,
):
    """
    Consulta o provedor sem manter transações de banco abertas.

    Cada resposta passa novamente pelas validações transacionais usadas
    pelo webhook. Uma falha em uma cobrança não interrompe as demais.
    """

    reference_time = at or timezone.now()
    payments = reconciliation_candidates(
        at=reference_time,
        limit=limit,
    )
    reconciled = 0
    failed = 0
    resolve_gateway = (
        gateway_getter or get_payment_gateway_for_payment
    )

    for payment in payments:
        try:
            gateway = resolve_gateway(payment)
            snapshot = gateway.fetch_payment(
                payment.provider_order_id
            )
            reconcile_payment_snapshot(
                payment_id=payment.id,
                snapshot=snapshot,
                at=reference_time,
            )
        except (PaymentGatewayError, PaymentConfirmationError) as error:
            failed += 1
            _record_attempt(
                payment_id=payment.id,
                at=reference_time,
                error_message=error,
            )
        else:
            reconciled += 1
            _record_attempt(
                payment_id=payment.id,
                at=reference_time,
            )

    return PaymentReconciliationBatchResult(
        selected=len(payments),
        reconciled=reconciled,
        failed=failed,
    )
