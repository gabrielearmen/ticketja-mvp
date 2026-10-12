from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.events.models import Event, EventStatus, SportCategory
from apps.orders.models import Order, OrderStatus
from apps.organizations.models import Organization, OrganizationStatus

from .gateways.base import (
    PaymentGatewayTemporaryError,
    PaymentSnapshot,
)
from .models import (
    Payment,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
)
from .reconciliation import reconcile_provider_payments


class PendingGateway:
    def __init__(self, payment):
        self.payment = payment

    def fetch_payment(self, provider_order_id):
        return PaymentSnapshot(
            provider_order_id=provider_order_id,
            provider_payment_id=self.payment.provider_payment_id,
            provider_status="pending",
            provider_status_detail="pending_waiting_transfer",
            amount=self.payment.amount,
            external_reference=self.payment.external_reference,
        )


class FailingGateway:
    def fetch_payment(self, provider_order_id):
        del provider_order_id
        raise PaymentGatewayTemporaryError(
            "Indisponibilidade temporária simulada."
        )


@override_settings(
    PAYMENT_RECONCILIATION_MIN_INTERVAL_MINUTES=5,
    PAYMENT_RECONCILIATION_LOOKBACK_DAYS=180,
)
class PaymentReconciliationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.buyer = get_user_model().objects.create_user(
            email="reconciliation@example.com",
            password="Senha-Segura!2026",
        )
        cls.organization = Organization.objects.create(
            name="Organização Conciliação",
            slug="organizacao-conciliacao",
            status=OrganizationStatus.APPROVED,
        )
        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Evento Conciliação",
            summary="Evento usado nos testes de conciliação.",
            sport_category=SportCategory.RUNNING,
            event_datetime=now + timedelta(days=30),
            city="Fortaleza",
            state="CE",
            address="Rua dos Testes, 100",
            capacity=10,
            status=EventStatus.PUBLISHED,
        )

    def create_payment(self):
        order = Order.objects.create(
            buyer=self.buyer,
            organization=self.organization,
            event=self.event,
            status=OrderStatus.AWAITING_PAYMENT,
            subtotal=Decimal("100.00"),
            service_fee=Decimal("0.00"),
            total=Decimal("100.00"),
            reservation_expires_at=(
                timezone.now() + timedelta(minutes=30)
            ),
        )
        return Payment.objects.create(
            order=order,
            attempt_number=1,
            provider=PaymentProvider.MERCADO_PAGO,
            method=PaymentMethod.PIX,
            status=PaymentStatus.PENDING,
            amount=Decimal("100.00"),
            provider_order_id="PAY-RECON-001",
            provider_payment_id="PAY-RECON-001",
            expires_at=order.reservation_expires_at,
        )

    def test_pending_payment_is_reconciled_and_audited(self):
        payment = self.create_payment()

        result = reconcile_provider_payments(
            gateway_getter=lambda item: PendingGateway(item),
        )

        payment.refresh_from_db()
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.reconciled, 1)
        self.assertEqual(result.failed, 0)
        self.assertEqual(payment.reconciliation_attempts, 1)
        self.assertIsNotNone(payment.last_reconciled_at)
        self.assertEqual(payment.last_reconciliation_error, "")

    def test_provider_failure_is_recorded_without_losing_payment(self):
        payment = self.create_payment()

        result = reconcile_provider_payments(
            gateway_getter=lambda item: FailingGateway(),
        )

        payment.refresh_from_db()
        self.assertEqual(result.failed, 1)
        self.assertEqual(payment.status, PaymentStatus.PENDING)
        self.assertEqual(payment.reconciliation_attempts, 1)
        self.assertIn(
            "Indisponibilidade temporária",
            payment.last_reconciliation_error,
        )

    def test_recently_reconciled_payment_is_not_selected_again(self):
        payment = self.create_payment()
        payment.last_reconciled_at = timezone.now()
        payment.save(update_fields=("last_reconciled_at",))

        result = reconcile_provider_payments(
            gateway_getter=lambda item: PendingGateway(item),
        )

        self.assertEqual(result.selected, 0)
