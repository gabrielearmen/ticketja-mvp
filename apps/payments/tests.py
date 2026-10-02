import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.events.models import (
    Event,
    EventStatus,
    SportCategory,
)
from apps.orders.models import (
    Order,
    OrderStatus,
)
from apps.organizations.models import (
    Organization,
    OrganizationStatus,
)

from .gateways.base import PaymentGateway
from .gateways.registry import (
    clear_payment_gateway_cache,
    get_payment_gateway,
)
from .models import (
    Payment,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
    PaymentWebhookEvent,
    WebhookProcessingStatus,
)


class DummyPaymentGateway(PaymentGateway):
    def create_pix_charge(self, request):
        raise NotImplementedError

    def fetch_payment(self, provider_payment_id):
        raise NotImplementedError

    def cancel_payment(self, provider_payment_id):
        raise NotImplementedError


class PaymentModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.buyer = user_model.objects.create_user(
            email="pagador@example.com",
            password="Senha-Segura!2026",
            first_name="Pagador",
        )

        cls.organization = Organization.objects.create(
            name="Organização Pagamentos",
            slug="organizacao-pagamentos",
            status=OrganizationStatus.APPROVED,
        )

        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Evento de Pagamentos",
            summary="Evento dos testes de pagamento.",
            sport_category=SportCategory.RUNNING,
            event_datetime=(
                timezone.now() + timedelta(days=30)
            ),
            city="Fortaleza",
            state="CE",
            address="Avenida de Testes, 100",
            capacity=100,
            status=EventStatus.PUBLISHED,
        )

    def create_order(self, **changes):
        data = {
            "buyer": self.buyer,
            "organization": self.organization,
            "event": self.event,
            "status": OrderStatus.AWAITING_PAYMENT,
            "subtotal": Decimal("100.00"),
            "service_fee": Decimal("10.00"),
            "total": Decimal("110.00"),
            "reservation_expires_at": (
                timezone.now() + timedelta(minutes=15)
            ),
        }

        data.update(changes)

        return Order.objects.create(**data)

    def create_payment(self, *, order=None, **changes):
        order = order or self.create_order()

        data = {
            "order": order,
            "attempt_number": 1,
            "provider": PaymentProvider.MERCADO_PAGO,
            "method": PaymentMethod.PIX,
            "status": PaymentStatus.CREATED,
            "amount": order.total,
            "platform_fee": Decimal("0.00"),
            "expires_at": order.reservation_expires_at,
        }

        data.update(changes)

        return Payment.objects.create(**data)

    def test_generates_external_reference_and_idempotency(self):
        payment = self.create_payment()

        self.assertRegex(
            payment.external_reference,
            r"^TJP-[A-HJ-NP-Z2-9]{18}$",
        )

        self.assertIsInstance(
            payment.idempotency_key,
            uuid.UUID,
        )

    def test_rejects_negative_amount(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_payment(
                    amount=Decimal("-1.00"),
                )

    def test_platform_fee_cannot_exceed_amount(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_payment(
                    amount=Decimal("110.00"),
                    platform_fee=Decimal("111.00"),
                )

    def test_only_one_open_attempt_per_order(self):
        order = self.create_order()

        self.create_payment(
            order=order,
            attempt_number=1,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_payment(
                    order=order,
                    attempt_number=2,
                    status=PaymentStatus.PENDING,
                )

    def test_new_attempt_is_allowed_after_rejection(self):
        order = self.create_order()

        first_payment = self.create_payment(
            order=order,
            attempt_number=1,
        )

        first_payment.status = PaymentStatus.REJECTED
        first_payment.save(update_fields=("status",))

        second_payment = self.create_payment(
            order=order,
            attempt_number=2,
        )

        self.assertEqual(
            second_payment.attempt_number,
            2,
        )

    def test_only_one_approved_payment_per_order(self):
        order = self.create_order()
        approved_at = timezone.now()

        self.create_payment(
            order=order,
            attempt_number=1,
            status=PaymentStatus.APPROVED,
            approved_at=approved_at,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_payment(
                    order=order,
                    attempt_number=2,
                    status=PaymentStatus.APPROVED,
                    approved_at=approved_at,
                )

    def test_approved_payment_requires_timestamp(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_payment(
                    status=PaymentStatus.APPROVED,
                    approved_at=None,
                )

    def test_provider_payment_id_is_unique_per_provider(self):
        self.create_payment(
            provider_payment_id="mp-payment-123",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_payment(
                    provider_payment_id="mp-payment-123",
                )

    def test_payment_amount_must_match_order_total(self):
        payment = self.create_payment()

        payment.amount = Decimal("99.00")

        with self.assertRaises(ValidationError):
            payment.full_clean()

    def test_free_order_uses_internal_processing(self):
        order = self.create_order(
            subtotal=Decimal("0.00"),
            service_fee=Decimal("0.00"),
            total=Decimal("0.00"),
        )

        payment = self.create_payment(
            order=order,
            provider=PaymentProvider.INTERNAL,
            method=PaymentMethod.FREE,
            amount=Decimal("0.00"),
        )

        payment.full_clean()

        self.assertEqual(
            payment.provider,
            PaymentProvider.INTERNAL,
        )

    def test_external_zero_value_payment_is_rejected(self):
        order = self.create_order(
            subtotal=Decimal("0.00"),
            service_fee=Decimal("0.00"),
            total=Decimal("0.00"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_payment(
                    order=order,
                    provider=PaymentProvider.MERCADO_PAGO,
                    method=PaymentMethod.PIX,
                    amount=Decimal("0.00"),
                )

    def test_model_does_not_store_card_data(self):
        field_names = {
            field.name
            for field in Payment._meta.get_fields()
        }

        forbidden_fields = {
            "card_number",
            "cardholder_name",
            "expiration_month",
            "expiration_year",
            "security_code",
            "cvv",
            "card_token",
        }

        self.assertTrue(
            field_names.isdisjoint(forbidden_fields)
        )


class PaymentWebhookEventModelTests(TestCase):
    def create_event(self, **changes):
        data = {
            "provider": PaymentProvider.MERCADO_PAGO,
            "notification_id": "notification-123",
            "event_type": "payment",
            "action": "payment.updated",
            "resource_id": "payment-456",
            "request_id": "request-789",
            "deduplication_key": "a" * 64,
            "payload_sha256": "b" * 64,
            "signature_valid": True,
            "processing_status": (
                WebhookProcessingStatus.RECEIVED
            ),
            "processing_attempts": 0,
            "processed_at": None,
        }

        data.update(changes)

        return PaymentWebhookEvent.objects.create(**data)

    def test_duplicate_notification_is_rejected(self):
        self.create_event()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_event(
                    deduplication_key="c" * 64,
                )

    def test_duplicate_deduplication_key_is_rejected(self):
        self.create_event()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_event(
                    notification_id="notification-999",
                )

    def test_processed_event_requires_timestamp(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_event(
                    processing_status=(
                        WebhookProcessingStatus.PROCESSED
                    ),
                    processed_at=None,
                )

    def test_webhook_model_does_not_store_raw_payload(self):
        field_names = {
            field.name
            for field in (
                PaymentWebhookEvent._meta.get_fields()
            )
        }

        self.assertNotIn(
            "payload",
            field_names,
        )

        self.assertNotIn(
            "raw_payload",
            field_names,
        )


class PaymentGatewayRegistryTests(TestCase):
    def tearDown(self):
        clear_payment_gateway_cache()

    @override_settings(
        PAYMENT_GATEWAY_CLASS=(
            "apps.payments.tests.DummyPaymentGateway"
        )
    )
    def test_registry_loads_configured_gateway(self):
        clear_payment_gateway_cache()

        gateway = get_payment_gateway()

        self.assertIsInstance(
            gateway,
            DummyPaymentGateway,
        )