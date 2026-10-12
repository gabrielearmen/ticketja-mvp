from datetime import timedelta
from decimal import Decimal

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.events.models import (
    Event,
    EventStatus,
    SportCategory,
    TicketLot,
    TicketType,
)
from apps.events.rules import commercial_configuration_errors
from apps.marketplace.crypto import encrypt_secret
from apps.marketplace.models import (
    FeeBearer,
    MarketplaceFeePolicy,
    OrganizationPaymentAccount,
    PaymentAccountStatus,
)
from apps.orders.services import create_reservation_order
from apps.organizations.models import Organization, OrganizationStatus


PAYMENT_FLOW_KEY = Fernet.generate_key().decode("ascii")


@override_settings(
    MARKETPLACE_PAYMENTS_ENABLED=True,
    MARKETPLACE_TOKEN_ENCRYPTION_KEYS=PAYMENT_FLOW_KEY,
)
class MarketplaceOrderFeeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.buyer = get_user_model().objects.create_user(
            email="fee-buyer@example.com",
            password="Senha-Segura!2026",
        )
        cls.organization = Organization.objects.create(
            name="Organização Comissão",
            slug="organizacao-comissao",
            status=OrganizationStatus.APPROVED,
        )
        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Evento Comissão",
            summary="Evento para validar comissão congelada.",
            sport_category=SportCategory.RUNNING,
            event_datetime=timezone.now() + timedelta(days=20),
            city="Fortaleza",
            state="CE",
            address="Rua Segura, 100",
            capacity=100,
            status=EventStatus.PUBLISHED,
        )
        cls.ticket_type = TicketType.objects.create(
            event=cls.event,
            name="Ingresso Geral",
            capacity=100,
            is_active=True,
        )
        cls.ticket_lot = TicketLot.objects.create(
            ticket_type=cls.ticket_type,
            name="Lote Comissão",
            price=Decimal("100.00"),
            quantity=100,
            sales_start=timezone.now() - timedelta(days=1),
            sales_end=timezone.now() + timedelta(days=10),
            is_active=True,
        )

    def test_buyer_fee_is_frozen_when_order_is_created(self):
        policy = MarketplaceFeePolicy.objects.create(
            name="Taxa padrão",
            fee_bearer=FeeBearer.BUYER,
            percentage_rate=Decimal("8.0000"),
            fixed_amount_per_ticket=Decimal("0.00"),
            effective_from=timezone.now() - timedelta(days=1),
            is_active=True,
        )

        result = create_reservation_order(
            buyer=self.buyer,
            ticket_lot_id=self.ticket_lot.id,
            quantity=2,
            idempotency_key=__import__("uuid").uuid4(),
        )

        self.assertEqual(result.order.subtotal, Decimal("200.00"))
        self.assertEqual(result.order.platform_fee, Decimal("16.00"))
        self.assertEqual(result.order.service_fee, Decimal("16.00"))
        self.assertEqual(result.order.total, Decimal("216.00"))
        self.assertEqual(result.order.fee_bearer, FeeBearer.BUYER)
        self.assertEqual(result.order.fee_policy_reference, policy.id)

    def test_organizer_fee_does_not_increase_buyer_total(self):
        MarketplaceFeePolicy.objects.create(
            name="Taxa absorvida",
            fee_bearer=FeeBearer.ORGANIZER,
            percentage_rate=Decimal("8.0000"),
            fixed_amount_per_ticket=Decimal("0.00"),
            effective_from=timezone.now() - timedelta(days=1),
            is_active=True,
        )

        result = create_reservation_order(
            buyer=self.buyer,
            ticket_lot_id=self.ticket_lot.id,
            quantity=1,
            idempotency_key=__import__("uuid").uuid4(),
        )

        self.assertEqual(result.order.platform_fee, Decimal("8.00"))
        self.assertEqual(result.order.service_fee, Decimal("0.00"))
        self.assertEqual(result.order.total, Decimal("100.00"))

    def test_connected_account_keeps_only_encrypted_token(self):
        account = OrganizationPaymentAccount.objects.create(
            organization=self.organization,
            status=PaymentAccountStatus.ACTIVE,
            provider_user_id="seller-123",
            is_live_mode=True,
            access_token_ciphertext=encrypt_secret("seller-token"),
            refresh_token_ciphertext=encrypt_secret("refresh-token"),
            access_token_expires_at=timezone.now() + timedelta(days=30),
            connected_at=timezone.now(),
        )

        self.assertNotIn("seller-token", account.access_token_ciphertext)

    def test_paid_event_cannot_publish_without_financial_setup(self):
        errors = commercial_configuration_errors(self.event)

        self.assertTrue(
            any("Conecte a conta Mercado Pago" in error for error in errors)
        )
        self.assertTrue(
            any("política de comissão" in error for error in errors)
        )

    def test_paid_event_is_financially_ready_after_account_and_policy(self):
        MarketplaceFeePolicy.objects.create(
            name="Política ativa",
            fee_bearer=FeeBearer.BUYER,
            percentage_rate=Decimal("8.0000"),
            effective_from=timezone.now() - timedelta(days=1),
            is_active=True,
        )
        OrganizationPaymentAccount.objects.create(
            organization=self.organization,
            status=PaymentAccountStatus.ACTIVE,
            provider_user_id="seller-ready",
            is_live_mode=True,
            access_token_ciphertext=encrypt_secret("seller-token"),
            refresh_token_ciphertext=encrypt_secret("refresh-token"),
            access_token_expires_at=timezone.now() + timedelta(days=30),
            connected_at=timezone.now(),
        )

        errors = commercial_configuration_errors(self.event)

        self.assertEqual(errors, [])
