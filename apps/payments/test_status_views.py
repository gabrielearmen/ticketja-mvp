from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.events.models import (
    Event,
    EventStatus,
    SportCategory,
    TicketLot,
    TicketType,
)
from apps.orders.models import (
    Order,
    OrderItem,
    OrderStatus,
)
from apps.organizations.models import (
    Organization,
    OrganizationStatus,
)

from .models import (
    Payment,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
)


class PaymentStatusViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        user_model = get_user_model()

        cls.buyer = user_model.objects.create_user(
            email="status@example.com",
            password="senha-forte-2026",
        )

        cls.other_buyer = user_model.objects.create_user(
            email="outro-status@example.com",
            password="senha-forte-2026",
        )

        cls.organization = Organization.objects.create(
            name="Organização Status",
            slug="organizacao-status",
            status=OrganizationStatus.APPROVED,
        )

        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Corrida Status",
            summary="Evento de teste.",
            sport_category=SportCategory.RUNNING,
            event_datetime=now + timedelta(days=30),
            city="Fortaleza",
            state="CE",
            address="Avenida dos Testes, 100",
            capacity=10,
            status=EventStatus.PUBLISHED,
            cover_image="events/covers/status.png",
        )

        cls.ticket_type = TicketType.objects.create(
            event=cls.event,
            name="Ingresso",
            description="Ingresso de teste.",
            capacity=10,
            is_active=True,
        )

        cls.ticket_lot = TicketLot.objects.create(
            ticket_type=cls.ticket_type,
            name="Lote único",
            price=Decimal("50.00"),
            quantity=10,
            sales_start=now - timedelta(days=1),
            sales_end=now + timedelta(days=20),
            is_active=True,
        )

    def setUp(self):
        now = timezone.now()

        self.order = Order.objects.create(
            buyer=self.buyer,
            organization=self.organization,
            event=self.event,
            status=OrderStatus.AWAITING_PAYMENT,
            subtotal=Decimal("50.00"),
            service_fee=Decimal("0.00"),
            total=Decimal("50.00"),
            reservation_expires_at=(
                now + timedelta(minutes=30)
            ),
        )

        OrderItem.objects.create(
            order=self.order,
            ticket_type=self.ticket_type,
            ticket_lot=self.ticket_lot,
            quantity=1,
            unit_price=Decimal("50.00"),
            subtotal=Decimal("50.00"),
        )

        self.payment = Payment.objects.create(
            order=self.order,
            attempt_number=1,
            provider=PaymentProvider.MERCADO_PAGO,
            method=PaymentMethod.PIX,
            status=PaymentStatus.PENDING,
            amount=Decimal("50.00"),
            platform_fee=Decimal("0.00"),
            provider_order_id="ORD-STATUS-TEST",
            provider_payment_id="PAY-STATUS-TEST",
            expires_at=self.order.reservation_expires_at,
        )

        self.url = reverse(
            "payments:status",
            kwargs={
                "public_code": self.order.public_code,
            },
        )

    def test_login_is_required(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)

    def test_buyer_cannot_read_another_buyers_order(self):
        self.client.force_login(self.other_buyer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_pending_payment_returns_pending_state(self):
        self.client.force_login(self.buyer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["state"],
            "pending",
        )
        self.assertFalse(
            response.json()["terminal"]
        )

    def test_approved_payment_returns_terminal_state(self):
        approved_at = timezone.now()

        self.order.status = OrderStatus.PAID
        self.order.save(
            update_fields=("status", "updated_at")
        )

        self.payment.status = PaymentStatus.APPROVED
        self.payment.approved_at = approved_at
        self.payment.save(
            update_fields=(
                "status",
                "approved_at",
                "updated_at",
            )
        )

        self.client.force_login(self.buyer)

        response = self.client.get(self.url)

        self.assertEqual(
            response.json()["state"],
            "approved",
        )
        self.assertTrue(
            response.json()["terminal"]
        )

    def test_expired_reservation_is_persisted(self):
        self.order.reservation_expires_at = (
            timezone.now() - timedelta(minutes=1)
        )

        self.order.save(
            update_fields=(
                "reservation_expires_at",
                "updated_at",
            )
        )

        self.client.force_login(self.buyer)

        response = self.client.get(self.url)

        self.order.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["state"],
            "expired",
        )
        self.assertEqual(
            self.order.status,
            OrderStatus.EXPIRED,
        )