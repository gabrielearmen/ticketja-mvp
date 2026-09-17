import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
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
from .services import create_reservation_order


class ReservationOrderCreationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.buyer = user_model.objects.create_user(
            email="reserva@example.com",
            password="Senha-Segura!2026",
            first_name="Comprador",
        )

        cls.other_buyer = user_model.objects.create_user(
            email="outra-reserva@example.com",
            password="Senha-Segura!2026",
            first_name="Outro",
        )

        cls.organization = Organization.objects.create(
            name="Organização de Reservas",
            slug="organizacao-de-reservas",
            status=OrganizationStatus.APPROVED,
        )

        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Evento para Reservas",
            summary="Evento usado nos testes de reserva.",
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
            name="Ingresso Reserva",
            description="Ingresso principal.",
            capacity=5,
            is_active=True,
        )

        cls.ticket_lot = TicketLot.objects.create(
            ticket_type=cls.ticket_type,
            name="Lote Reserva",
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

        cls.second_ticket_type = TicketType.objects.create(
            event=cls.event,
            name="Segundo Ingresso",
            description="Outra opção.",
            capacity=5,
            is_active=True,
        )

        cls.second_ticket_lot = TicketLot.objects.create(
            ticket_type=cls.second_ticket_type,
            name="Segundo Lote",
            price=Decimal("70.00"),
            quantity=5,
            sales_start=(
                timezone.now() - timedelta(days=1)
            ),
            sales_end=(
                timezone.now() + timedelta(days=10)
            ),
            is_active=True,
        )

    def create_existing_commitment(
        self,
        *,
        quantity,
        status,
        reservation_expires_at=None,
    ):
        subtotal = self.ticket_lot.price * quantity

        order = Order.objects.create(
            buyer=self.buyer,
            organization=self.organization,
            event=self.event,
            status=status,
            subtotal=subtotal,
            service_fee=Decimal("0.00"),
            total=subtotal,
            reservation_expires_at=(
                reservation_expires_at
            ),
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

    def test_creates_reservation_and_freezes_values(self):
        before_creation = timezone.now()

        result = create_reservation_order(
            buyer=self.buyer,
            ticket_lot_id=self.ticket_lot.id,
            quantity=2,
            idempotency_key=uuid.uuid4(),
        )

        after_creation = timezone.now()

        self.assertTrue(result.created)

        order = result.order

        self.assertEqual(
            order.status,
            OrderStatus.AWAITING_PAYMENT,
        )
        self.assertEqual(order.buyer, self.buyer)
        self.assertEqual(
            order.organization,
            self.organization,
        )
        self.assertEqual(order.event, self.event)
        self.assertEqual(
            order.subtotal,
            Decimal("100.00"),
        )
        self.assertEqual(
            order.service_fee,
            Decimal("0.00"),
        )
        self.assertEqual(
            order.total,
            Decimal("100.00"),
        )

        minimum_expiration = (
            before_creation + timedelta(minutes=15)
        )
        maximum_expiration = (
            after_creation + timedelta(minutes=15)
        )

        self.assertGreaterEqual(
            order.reservation_expires_at,
            minimum_expiration,
        )
        self.assertLessEqual(
            order.reservation_expires_at,
            maximum_expiration,
        )

        item = order.items.get()

        self.assertEqual(item.quantity, 2)
        self.assertEqual(
            item.unit_price,
            Decimal("50.00"),
        )
        self.assertEqual(
            item.subtotal,
            Decimal("100.00"),
        )

        self.ticket_lot.price = Decimal("90.00")
        self.ticket_lot.save(update_fields=["price"])

        item.refresh_from_db()

        self.assertEqual(
            item.unit_price,
            Decimal("50.00"),
        )
        self.assertEqual(
            item.subtotal,
            Decimal("100.00"),
        )

    @override_settings(ORDER_RESERVATION_MINUTES=25)
    def test_uses_configured_reservation_duration(self):
        before_creation = timezone.now()

        result = create_reservation_order(
            buyer=self.buyer,
            ticket_lot_id=self.ticket_lot.id,
            quantity=1,
            idempotency_key=uuid.uuid4(),
        )

        minimum_expiration = (
            before_creation + timedelta(minutes=25)
        )

        self.assertGreaterEqual(
            result.order.reservation_expires_at,
            minimum_expiration,
        )

    def test_repeated_request_returns_same_order(self):
        operation_key = uuid.uuid4()

        first_result = create_reservation_order(
            buyer=self.buyer,
            ticket_lot_id=self.ticket_lot.id,
            quantity=2,
            idempotency_key=operation_key,
        )

        original_expiration = (
            first_result.order.reservation_expires_at
        )

        second_result = create_reservation_order(
            buyer=self.buyer,
            ticket_lot_id=self.ticket_lot.id,
            quantity=2,
            idempotency_key=operation_key,
        )

        self.assertTrue(first_result.created)
        self.assertFalse(second_result.created)

        self.assertEqual(
            first_result.order.id,
            second_result.order.id,
        )
        self.assertEqual(
            second_result.order.reservation_expires_at,
            original_expiration,
        )
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)

    def test_same_key_rejects_different_quantity(self):
        operation_key = uuid.uuid4()

        create_reservation_order(
            buyer=self.buyer,
            ticket_lot_id=self.ticket_lot.id,
            quantity=1,
            idempotency_key=operation_key,
        )

        with self.assertRaises(ValidationError):
            create_reservation_order(
                buyer=self.buyer,
                ticket_lot_id=self.ticket_lot.id,
                quantity=2,
                idempotency_key=operation_key,
            )

        self.assertEqual(Order.objects.count(), 1)

    def test_same_key_rejects_different_lot(self):
        operation_key = uuid.uuid4()

        create_reservation_order(
            buyer=self.buyer,
            ticket_lot_id=self.ticket_lot.id,
            quantity=1,
            idempotency_key=operation_key,
        )

        with self.assertRaises(ValidationError):
            create_reservation_order(
                buyer=self.buyer,
                ticket_lot_id=self.second_ticket_lot.id,
                quantity=1,
                idempotency_key=operation_key,
            )

        self.assertEqual(Order.objects.count(), 1)

    def test_same_key_rejects_different_buyer(self):
        operation_key = uuid.uuid4()

        create_reservation_order(
            buyer=self.buyer,
            ticket_lot_id=self.ticket_lot.id,
            quantity=1,
            idempotency_key=operation_key,
        )

        with self.assertRaises(ValidationError):
            create_reservation_order(
                buyer=self.other_buyer,
                ticket_lot_id=self.ticket_lot.id,
                quantity=1,
                idempotency_key=operation_key,
            )

        self.assertEqual(Order.objects.count(), 1)

    def test_paid_quantity_prevents_overbooking(self):
        self.create_existing_commitment(
            quantity=4,
            status=OrderStatus.PAID,
        )

        with self.assertRaises(ValidationError) as error:
            create_reservation_order(
                buyer=self.buyer,
                ticket_lot_id=self.ticket_lot.id,
                quantity=2,
                idempotency_key=uuid.uuid4(),
            )

        self.assertIn(
            "Restam 1 vaga(s)",
            str(error.exception),
        )

        self.assertEqual(Order.objects.count(), 1)

    def test_expired_reservation_releases_availability(self):
        self.create_existing_commitment(
            quantity=5,
            status=OrderStatus.AWAITING_PAYMENT,
            reservation_expires_at=(
                timezone.now() - timedelta(minutes=1)
            ),
        )

        result = create_reservation_order(
            buyer=self.other_buyer,
            ticket_lot_id=self.ticket_lot.id,
            quantity=5,
            idempotency_key=uuid.uuid4(),
        )

        self.assertTrue(result.created)
        self.assertEqual(
            result.order.items.get().quantity,
            5,
        )

    def test_invalid_quantities_do_not_create_order(self):
        invalid_quantities = (
            0,
            -1,
            "1",
            True,
        )

        for quantity in invalid_quantities:
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValidationError):
                    create_reservation_order(
                        buyer=self.buyer,
                        ticket_lot_id=self.ticket_lot.id,
                        quantity=quantity,
                        idempotency_key=uuid.uuid4(),
                    )

        self.assertEqual(Order.objects.count(), 0)

    def test_invalid_idempotency_key_is_rejected(self):
        with self.assertRaises(ValidationError):
            create_reservation_order(
                buyer=self.buyer,
                ticket_lot_id=self.ticket_lot.id,
                quantity=1,
                idempotency_key="chave-invalida",
            )

        self.assertEqual(Order.objects.count(), 0)

    def test_inactive_buyer_is_rejected(self):
        self.buyer.is_active = False
        self.buyer.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError):
            create_reservation_order(
                buyer=self.buyer,
                ticket_lot_id=self.ticket_lot.id,
                quantity=1,
                idempotency_key=uuid.uuid4(),
            )

        self.assertEqual(Order.objects.count(), 0)

    def test_free_lot_creates_zero_value_order(self):
        free_type = TicketType.objects.create(
            event=self.event,
            name="Ingresso Gratuito",
            description="Ingresso sem cobrança.",
            capacity=2,
            is_active=True,
        )

        free_lot = TicketLot.objects.create(
            ticket_type=free_type,
            name="Lote Gratuito",
            price=Decimal("0.00"),
            quantity=2,
            sales_start=(
                timezone.now() - timedelta(days=1)
            ),
            sales_end=(
                timezone.now() + timedelta(days=10)
            ),
            is_active=True,
        )

        result = create_reservation_order(
            buyer=self.buyer,
            ticket_lot_id=free_lot.id,
            quantity=2,
            idempotency_key=uuid.uuid4(),
        )

        self.assertEqual(
            result.order.subtotal,
            Decimal("0.00"),
        )
        self.assertEqual(
            result.order.service_fee,
            Decimal("0.00"),
        )
        self.assertEqual(
            result.order.total,
            Decimal("0.00"),
        )

    def test_unavailable_lot_does_not_create_order(self):
        self.ticket_lot.sales_start = (
            timezone.now() + timedelta(days=1)
        )
        self.ticket_lot.sales_end = (
            timezone.now() + timedelta(days=5)
        )
        self.ticket_lot.save(
            update_fields=["sales_start", "sales_end"]
        )

        with self.assertRaises(ValidationError):
            create_reservation_order(
                buyer=self.buyer,
                ticket_lot_id=self.ticket_lot.id,
                quantity=1,
                idempotency_key=uuid.uuid4(),
            )

        self.assertEqual(Order.objects.count(), 0)