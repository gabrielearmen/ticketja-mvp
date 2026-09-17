import uuid
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.events.models import (
    Event,
    EventStatus,
    SportCategory,
    TicketLot,
    TicketType,
)
from apps.organizations.models import (
    Organization,
    OrganizationStatus,
)

from .models import Order, OrderItem, OrderStatus
from .services import (
    create_reservation_order,
    expire_order_reservation,
    expire_stale_reservations,
)


class OrderExpirationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.buyer = user_model.objects.create_user(
            email="expiracao@example.com",
            password="Senha-Segura!2026",
        )

        cls.other_buyer = user_model.objects.create_user(
            email="expiracao-outro@example.com",
            password="Senha-Segura!2026",
        )

        cls.organization = Organization.objects.create(
            name="Organização Expiração",
            slug="organizacao-expiracao",
            status=OrganizationStatus.APPROVED,
        )

        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Evento de Expiração",
            summary="Evento usado nos testes de expiração.",
            sport_category=SportCategory.RUNNING,
            event_datetime=(
                timezone.now() + timedelta(days=30)
            ),
            city="Fortaleza",
            state="CE",
            address="Avenida Beira Mar, 1000",
            capacity=100,
            status=EventStatus.PUBLISHED,
        )

        cls.ticket_type = TicketType.objects.create(
            event=cls.event,
            name="Ingresso Expiração",
            capacity=5,
            is_active=True,
        )

        cls.ticket_lot = TicketLot.objects.create(
            ticket_type=cls.ticket_type,
            name="Lote Expiração",
            price=Decimal("50.00"),
            quantity=5,
            sales_start=(
                timezone.now() - timedelta(days=1)
            ),
            sales_end=(
                timezone.now() + timedelta(days=10)
            ),
            is_active=True,
        )

    def create_order(
        self,
        *,
        status,
        expiration=None,
        buyer=None,
        quantity=1,
    ):
        subtotal = self.ticket_lot.price * quantity

        order = Order.objects.create(
            buyer=buyer or self.buyer,
            organization=self.organization,
            event=self.event,
            status=status,
            subtotal=subtotal,
            service_fee=Decimal("0.00"),
            total=subtotal,
            reservation_expires_at=expiration,
        )

        OrderItem.objects.create(
            order=order,
            ticket_type=self.ticket_type,
            ticket_lot=self.ticket_lot,
            quantity=quantity,
            unit_price=self.ticket_lot.price,
            subtotal=subtotal,
        )

        return order

    def test_expiration_is_persisted_at_exact_boundary(self):
        reference_time = timezone.now()

        order = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            expiration=reference_time,
        )

        original_expiration = order.reservation_expires_at

        result = expire_order_reservation(
            order_id=order.id,
            at=reference_time,
        )

        order.refresh_from_db()

        self.assertTrue(result.expired)
        self.assertEqual(
            order.status,
            OrderStatus.EXPIRED,
        )
        self.assertEqual(
            order.reservation_expires_at,
            original_expiration,
        )

    def test_future_reservation_is_not_expired(self):
        order = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            expiration=(
                timezone.now() + timedelta(minutes=10)
            ),
        )

        result = expire_order_reservation(
            order_id=order.id,
        )

        order.refresh_from_db()

        self.assertFalse(result.expired)
        self.assertEqual(
            order.status,
            OrderStatus.AWAITING_PAYMENT,
        )

    def test_paid_order_is_never_expired(self):
        order = self.create_order(
            status=OrderStatus.PAID,
            expiration=(
                timezone.now() - timedelta(minutes=10)
            ),
        )

        result = expire_order_reservation(
            order_id=order.id,
        )

        order.refresh_from_db()

        self.assertFalse(result.expired)
        self.assertEqual(order.status, OrderStatus.PAID)

    def test_expiration_is_idempotent(self):
        order = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            expiration=(
                timezone.now() - timedelta(minutes=1)
            ),
        )

        first_result = expire_order_reservation(
            order_id=order.id,
        )

        second_result = expire_order_reservation(
            order_id=order.id,
        )

        self.assertTrue(first_result.expired)
        self.assertFalse(second_result.expired)

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            OrderStatus.EXPIRED,
        )

    def test_sweep_expires_only_stale_reservations(self):
        expired_order = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            expiration=(
                timezone.now() - timedelta(minutes=1)
            ),
        )

        future_order = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            expiration=(
                timezone.now() + timedelta(minutes=10)
            ),
            buyer=self.other_buyer,
        )

        paid_order = self.create_order(
            status=OrderStatus.PAID,
            expiration=(
                timezone.now() - timedelta(minutes=10)
            ),
        )

        expired_count = expire_stale_reservations()

        self.assertEqual(expired_count, 1)

        expired_order.refresh_from_db()
        future_order.refresh_from_db()
        paid_order.refresh_from_db()

        self.assertEqual(
            expired_order.status,
            OrderStatus.EXPIRED,
        )
        self.assertEqual(
            future_order.status,
            OrderStatus.AWAITING_PAYMENT,
        )
        self.assertEqual(
            paid_order.status,
            OrderStatus.PAID,
        )

    def test_sweep_respects_batch_size(self):
        first_order = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            expiration=(
                timezone.now() - timedelta(minutes=2)
            ),
        )

        second_order = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            expiration=(
                timezone.now() - timedelta(minutes=1)
            ),
            buyer=self.other_buyer,
        )

        expired_count = expire_stale_reservations(
            batch_size=1,
        )

        self.assertEqual(expired_count, 1)

        statuses = {
            Order.objects.get(id=first_order.id).status,
            Order.objects.get(id=second_order.id).status,
        }

        self.assertEqual(
            statuses,
            {
                OrderStatus.EXPIRED,
                OrderStatus.AWAITING_PAYMENT,
            },
        )

    def test_invalid_batch_size_is_rejected(self):
        invalid_values = (
            0,
            -1,
            True,
            "10",
        )

        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    expire_stale_reservations(
                        batch_size=value,
                    )

    def test_management_command_persists_expiration(self):
        order = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            expiration=(
                timezone.now() - timedelta(minutes=1)
            ),
        )

        output = StringIO()

        call_command(
            "expire_reservations",
            batch_size=10,
            stdout=output,
        )

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            OrderStatus.EXPIRED,
        )
        self.assertIn(
            "1 reserva(s) expirada(s).",
            output.getvalue(),
        )

    def test_exact_capacity_can_be_reserved_only_once(self):
        first_result = create_reservation_order(
            buyer=self.buyer,
            ticket_lot_id=self.ticket_lot.id,
            quantity=5,
            idempotency_key=uuid.uuid4(),
        )

        self.assertTrue(first_result.created)

        with self.assertRaises(ValidationError):
            create_reservation_order(
                buyer=self.other_buyer,
                ticket_lot_id=self.ticket_lot.id,
                quantity=1,
                idempotency_key=uuid.uuid4(),
            )

        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)

    def test_extremely_large_quantity_is_rejected(self):
        with self.assertRaises(ValidationError):
            create_reservation_order(
                buyer=self.buyer,
                ticket_lot_id=self.ticket_lot.id,
                quantity=1_000_000_000,
                idempotency_key=uuid.uuid4(),
            )

        self.assertEqual(Order.objects.count(), 0)