import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
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

from .models import (
    Order,
    OrderItem,
    OrderStatus,
)


class OrderModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.buyer_a = user_model.objects.create_user(
            email="comprador-a@example.com",
            password="Senha-Segura!2026",
            first_name="Comprador",
            last_name="A",
        )

        cls.buyer_b = user_model.objects.create_user(
            email="comprador-b@example.com",
            password="Senha-Segura!2026",
            first_name="Comprador",
            last_name="B",
        )

        cls.organization_a = Organization.objects.create(
            name="Organização de Pedidos A",
            slug="organizacao-pedidos-a",
            status=OrganizationStatus.APPROVED,
        )

        cls.organization_b = Organization.objects.create(
            name="Organização de Pedidos B",
            slug="organizacao-pedidos-b",
            status=OrganizationStatus.APPROVED,
        )

        cls.event_a = cls.create_event(
            organization=cls.organization_a,
            title="Evento de Pedidos A",
        )

        cls.event_b = cls.create_event(
            organization=cls.organization_b,
            title="Evento de Pedidos B",
        )

        cls.ticket_type_a = TicketType.objects.create(
            event=cls.event_a,
            name="Ingresso Evento A",
            description="Ingresso utilizado nos testes.",
            capacity=100,
            is_active=True,
        )

        cls.ticket_type_b = TicketType.objects.create(
            event=cls.event_b,
            name="Ingresso Evento B",
            description="Ingresso de outra organização.",
            capacity=100,
            is_active=True,
        )

        cls.ticket_lot_a = cls.create_ticket_lot(
            ticket_type=cls.ticket_type_a,
            name="Primeiro Lote A",
            price=Decimal("80.00"),
        )

        cls.ticket_lot_b = cls.create_ticket_lot(
            ticket_type=cls.ticket_type_b,
            name="Primeiro Lote B",
            price=Decimal("120.00"),
        )

    @classmethod
    def create_event(cls, *, organization, title):
        return Event.objects.create(
            organization=organization,
            title=title,
            summary="Evento criado para os testes de pedidos.",
            sport_category=SportCategory.RUNNING,
            event_datetime=(
                timezone.now() + timedelta(days=30)
            ),
            city="Fortaleza",
            state="CE",
            address="Avenida Beira Mar, 1000",
            capacity=500,
            status=EventStatus.PUBLISHED,
        )

    @classmethod
    def create_ticket_lot(
        cls,
        *,
        ticket_type,
        name,
        price,
    ):
        return TicketLot.objects.create(
            ticket_type=ticket_type,
            name=name,
            price=price,
            quantity=100,
            sales_start=(
                timezone.now() - timedelta(days=1)
            ),
            sales_end=(
                timezone.now() + timedelta(days=10)
            ),
            is_active=True,
        )

    def create_order(self, **changes):
        data = {
            "buyer": self.buyer_a,
            "organization": self.organization_a,
            "event": self.event_a,
            "status": OrderStatus.DRAFT,
            "subtotal": Decimal("100.00"),
            "service_fee": Decimal("10.00"),
            "total": Decimal("110.00"),
            "reservation_expires_at": None,
        }

        data.update(changes)

        return Order.objects.create(**data)

    def create_order_item(self, *, order, **changes):
        data = {
            "order": order,
            "ticket_type": self.ticket_type_a,
            "ticket_lot": self.ticket_lot_a,
            "quantity": 2,
            "unit_price": Decimal("80.00"),
            "subtotal": Decimal("160.00"),
        }

        data.update(changes)

        return OrderItem.objects.create(**data)

    def test_public_code_and_idempotency_are_generated(self):
        first_order = self.create_order()
        second_order = self.create_order()

        self.assertRegex(
            first_order.public_code,
            r"^TJ-[A-HJ-NP-Z2-9]{12}$",
        )

        self.assertNotEqual(
            first_order.public_code,
            second_order.public_code,
        )

        self.assertIsInstance(
            first_order.idempotency_key,
            uuid.UUID,
        )

        self.assertNotEqual(
            first_order.idempotency_key,
            second_order.idempotency_key,
        )

    def test_public_code_must_be_unique(self):
        existing_order = self.create_order()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_order(
                    public_code=existing_order.public_code,
                )

    def test_idempotency_key_must_be_unique(self):
        existing_order = self.create_order()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_order(
                    idempotency_key=(
                        existing_order.idempotency_key
                    ),
                )

    def test_order_rejects_negative_monetary_values(self):
        invalid_scenarios = (
            {
                "subtotal": Decimal("-1.00"),
                "service_fee": Decimal("1.00"),
                "total": Decimal("0.00"),
            },
            {
                "subtotal": Decimal("1.00"),
                "service_fee": Decimal("-1.00"),
                "total": Decimal("0.00"),
            },
            {
                "subtotal": Decimal("0.00"),
                "service_fee": Decimal("0.00"),
                "total": Decimal("-1.00"),
            },
        )

        for values in invalid_scenarios:
            with self.subTest(values=values):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        self.create_order(**values)

    def test_order_total_must_equal_subtotal_plus_fee(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_order(
                    subtotal=Decimal("100.00"),
                    service_fee=Decimal("10.00"),
                    total=Decimal("999.00"),
                )

    def test_order_status_must_be_valid(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_order(
                    status="status_inexistente",
                )

    def test_awaiting_payment_requires_expiration(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_order(
                    status=OrderStatus.AWAITING_PAYMENT,
                    reservation_expires_at=None,
                )

    def test_order_rejects_event_from_another_organization(self):
        order = Order(
            buyer=self.buyer_a,
            organization=self.organization_a,
            event=self.event_b,
            status=OrderStatus.DRAFT,
            subtotal=Decimal("0.00"),
            service_fee=Decimal("0.00"),
            total=Decimal("0.00"),
        )

        with self.assertRaises(ValidationError) as error:
            order.full_clean()

        self.assertIn(
            "organization",
            error.exception.message_dict,
        )

    def test_order_querysets_keep_tenant_and_buyer_isolation(self):
        order_a = self.create_order()

        order_b = self.create_order(
            organization=self.organization_b,
            event=self.event_b,
        )

        order_from_another_buyer = self.create_order(
            buyer=self.buyer_b,
        )

        organization_a_ids = set(
            Order.objects
            .for_organization(self.organization_a)
            .values_list("id", flat=True)
        )

        buyer_a_ids = set(
            Order.objects
            .for_buyer(self.buyer_a)
            .values_list("id", flat=True)
        )

        self.assertIn(order_a.id, organization_a_ids)
        self.assertIn(
            order_from_another_buyer.id,
            organization_a_ids,
        )
        self.assertNotIn(order_b.id, organization_a_ids)

        self.assertIn(order_a.id, buyer_a_ids)
        self.assertIn(order_b.id, buyer_a_ids)
        self.assertNotIn(
            order_from_another_buyer.id,
            buyer_a_ids,
        )

    def test_reservation_state_properties(self):
        active_reservation = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            reservation_expires_at=(
                timezone.now() + timedelta(minutes=15)
            ),
        )

        expired_reservation = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            reservation_expires_at=(
                timezone.now() - timedelta(minutes=1)
            ),
        )

        paid_order = self.create_order(
            status=OrderStatus.PAID,
        )

        refunded_order = self.create_order(
            status=OrderStatus.REFUNDED,
        )

        self.assertTrue(
            active_reservation.is_reservation_active
        )
        self.assertTrue(active_reservation.holds_inventory)
        self.assertFalse(active_reservation.is_expirable)

        self.assertFalse(
            expired_reservation.is_reservation_active
        )
        self.assertFalse(expired_reservation.holds_inventory)
        self.assertTrue(expired_reservation.is_expirable)

        self.assertTrue(paid_order.holds_inventory)
        self.assertFalse(refunded_order.holds_inventory)

    def test_inventory_queryset_counts_only_valid_orders(self):
        active_reservation = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            reservation_expires_at=(
                timezone.now() + timedelta(minutes=15)
            ),
        )

        expired_reservation = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            reservation_expires_at=(
                timezone.now() - timedelta(minutes=1)
            ),
        )

        paid_order = self.create_order(
            status=OrderStatus.PAID,
        )

        draft_order = self.create_order(
            status=OrderStatus.DRAFT,
        )

        refunded_order = self.create_order(
            status=OrderStatus.REFUNDED,
        )

        holding_ids = set(
            Order.objects
            .holding_inventory()
            .values_list("id", flat=True)
        )

        self.assertIn(active_reservation.id, holding_ids)
        self.assertIn(paid_order.id, holding_ids)

        self.assertNotIn(
            expired_reservation.id,
            holding_ids,
        )
        self.assertNotIn(draft_order.id, holding_ids)
        self.assertNotIn(refunded_order.id, holding_ids)

    def test_expired_reservations_queryset(self):
        active_reservation = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            reservation_expires_at=(
                timezone.now() + timedelta(minutes=15)
            ),
        )

        expired_reservation = self.create_order(
            status=OrderStatus.AWAITING_PAYMENT,
            reservation_expires_at=(
                timezone.now() - timedelta(minutes=1)
            ),
        )

        expired_ids = set(
            Order.objects
            .expired_reservations()
            .values_list("id", flat=True)
        )

        self.assertIn(expired_reservation.id, expired_ids)
        self.assertNotIn(active_reservation.id, expired_ids)

    def test_order_item_quantity_must_be_positive(self):
        order = self.create_order()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_order_item(
                    order=order,
                    quantity=0,
                    subtotal=Decimal("0.00"),
                )

    def test_order_item_rejects_negative_values(self):
        order = self.create_order()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_order_item(
                    order=order,
                    quantity=1,
                    unit_price=Decimal("-10.00"),
                    subtotal=Decimal("-10.00"),
                )

    def test_item_subtotal_must_equal_price_times_quantity(self):
        order = self.create_order()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_order_item(
                    order=order,
                    quantity=2,
                    unit_price=Decimal("80.00"),
                    subtotal=Decimal("10.00"),
                )

    def test_same_lot_can_appear_only_once_per_order(self):
        order = self.create_order()

        self.create_order_item(order=order)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_order_item(order=order)

    def test_lot_must_belong_to_informed_ticket_type(self):
        order = self.create_order()

        another_type_from_same_event = (
            TicketType.objects.create(
                event=self.event_a,
                name="Outro Ingresso Evento A",
                description="Outro tipo do mesmo evento.",
                capacity=50,
                is_active=True,
            )
        )

        item = OrderItem(
            order=order,
            ticket_type=another_type_from_same_event,
            ticket_lot=self.ticket_lot_a,
            quantity=1,
            unit_price=Decimal("80.00"),
            subtotal=Decimal("80.00"),
        )

        with self.assertRaises(ValidationError) as error:
            item.full_clean()

        self.assertIn(
            "ticket_lot",
            error.exception.message_dict,
        )

    def test_ticket_type_must_belong_to_order_event(self):
        order = self.create_order()

        item = OrderItem(
            order=order,
            ticket_type=self.ticket_type_b,
            ticket_lot=self.ticket_lot_b,
            quantity=1,
            unit_price=Decimal("120.00"),
            subtotal=Decimal("120.00"),
        )

        with self.assertRaises(ValidationError) as error:
            item.full_clean()

        self.assertIn(
            "ticket_type",
            error.exception.message_dict,
        )

    def test_unit_price_remains_frozen_when_lot_price_changes(self):
        order = self.create_order()

        item = self.create_order_item(
            order=order,
            quantity=1,
            unit_price=self.ticket_lot_a.price,
            subtotal=self.ticket_lot_a.price,
        )

        original_unit_price = item.unit_price

        self.ticket_lot_a.price = Decimal("150.00")
        self.ticket_lot_a.save(update_fields=["price"])

        item.refresh_from_db()

        self.assertEqual(
            item.unit_price,
            original_unit_price,
        )
        self.assertEqual(
            item.unit_price,
            Decimal("80.00"),
        )
        self.assertEqual(
            item.subtotal,
            Decimal("80.00"),
        )