from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
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

from .availability import (
    TicketLotAvailabilityStatus,
    calculate_ticket_lot_availability,
    lock_ticket_lot_and_calculate_availability,
    validate_reservation_quantity,
)
from .models import Order, OrderItem, OrderStatus


class TicketLotAvailabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.buyer = user_model.objects.create_user(
            email="disponibilidade@example.com",
            password="Senha-Segura!2026",
            first_name="Comprador",
        )

        cls.organization = Organization.objects.create(
            name="Organização Disponibilidade",
            slug="organizacao-disponibilidade",
            status=OrganizationStatus.APPROVED,
        )

        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Evento com Disponibilidade",
            summary="Evento utilizado nos testes de estoque.",
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
            name="Ingresso Principal",
            description="Ingresso principal do evento.",
            capacity=10,
            is_active=True,
        )

        cls.ticket_lot = TicketLot.objects.create(
            ticket_type=cls.ticket_type,
            name="Lote Principal",
            price=Decimal("50.00"),
            quantity=10,
            sales_start=(
                timezone.now() - timedelta(days=1)
            ),
            sales_end=(
                timezone.now() + timedelta(days=10)
            ),
            is_active=True,
        )

    def create_committed_item(
        self,
        *,
        quantity,
        status,
        ticket_lot=None,
        reservation_expires_at=None,
    ):
        selected_lot = ticket_lot or self.ticket_lot
        subtotal = selected_lot.price * quantity

        order = Order.objects.create(
            buyer=self.buyer,
            organization=(
                selected_lot
                .ticket_type
                .event
                .organization
            ),
            event=selected_lot.ticket_type.event,
            status=status,
            subtotal=subtotal,
            service_fee=Decimal("0.00"),
            total=subtotal,
            reservation_expires_at=(
                reservation_expires_at
            ),
        )

        item = OrderItem.objects.create(
            order=order,
            ticket_type=selected_lot.ticket_type,
            ticket_lot=selected_lot,
            quantity=quantity,
            unit_price=selected_lot.price,
            subtotal=subtotal,
        )

        return order, item

    def test_empty_lot_reports_full_availability(self):
        availability = calculate_ticket_lot_availability(
            ticket_lot=self.ticket_lot
        )

        self.assertEqual(availability.total_quantity, 10)
        self.assertEqual(availability.committed_quantity, 0)
        self.assertEqual(availability.available_quantity, 10)
        self.assertEqual(
            availability.status,
            TicketLotAvailabilityStatus.AVAILABLE,
        )
        self.assertTrue(availability.is_available)

    def test_paid_orders_reduce_availability(self):
        self.create_committed_item(
            quantity=3,
            status=OrderStatus.PAID,
        )

        availability = calculate_ticket_lot_availability(
            ticket_lot=self.ticket_lot
        )

        self.assertEqual(availability.committed_quantity, 3)
        self.assertEqual(availability.available_quantity, 7)

    def test_active_reservations_reduce_availability(self):
        self.create_committed_item(
            quantity=4,
            status=OrderStatus.AWAITING_PAYMENT,
            reservation_expires_at=(
                timezone.now() + timedelta(minutes=15)
            ),
        )

        availability = calculate_ticket_lot_availability(
            ticket_lot=self.ticket_lot
        )

        self.assertEqual(availability.committed_quantity, 4)
        self.assertEqual(availability.available_quantity, 6)

    def test_non_holding_orders_do_not_reduce_availability(self):
        scenarios = (
            (
                OrderStatus.AWAITING_PAYMENT,
                timezone.now() - timedelta(minutes=1),
            ),
            (OrderStatus.DRAFT, None),
            (OrderStatus.EXPIRED, None),
            (OrderStatus.CANCELED, None),
            (OrderStatus.REFUNDED, None),
        )

        for status, expiration in scenarios:
            self.create_committed_item(
                quantity=1,
                status=status,
                reservation_expires_at=expiration,
            )

        availability = calculate_ticket_lot_availability(
            ticket_lot=self.ticket_lot
        )

        self.assertEqual(availability.committed_quantity, 0)
        self.assertEqual(availability.available_quantity, 10)

    def test_calculation_is_isolated_by_lot(self):
        another_type = TicketType.objects.create(
            event=self.event,
            name="Outro Tipo de Ingresso",
            description="Outro tipo para isolamento.",
            capacity=10,
            is_active=True,
        )

        another_lot = TicketLot.objects.create(
            ticket_type=another_type,
            name="Outro Lote",
            price=Decimal("70.00"),
            quantity=10,
            sales_start=(
                timezone.now() - timedelta(days=1)
            ),
            sales_end=(
                timezone.now() + timedelta(days=10)
            ),
            is_active=True,
        )

        self.create_committed_item(
            quantity=3,
            status=OrderStatus.PAID,
            ticket_lot=self.ticket_lot,
        )

        self.create_committed_item(
            quantity=8,
            status=OrderStatus.PAID,
            ticket_lot=another_lot,
        )

        availability = calculate_ticket_lot_availability(
            ticket_lot=self.ticket_lot
        )

        self.assertEqual(availability.committed_quantity, 3)
        self.assertEqual(availability.available_quantity, 7)

    def test_sold_out_lot_is_identified(self):
        self.create_committed_item(
            quantity=10,
            status=OrderStatus.PAID,
        )

        availability = calculate_ticket_lot_availability(
            ticket_lot=self.ticket_lot
        )

        self.assertEqual(availability.available_quantity, 0)
        self.assertEqual(
            availability.status,
            TicketLotAvailabilityStatus.SOLD_OUT,
        )
        self.assertFalse(availability.is_available)

    def test_scheduled_lot_is_identified(self):
        self.ticket_lot.sales_start = (
            timezone.now() + timedelta(days=1)
        )
        self.ticket_lot.sales_end = (
            timezone.now() + timedelta(days=5)
        )
        self.ticket_lot.save(
            update_fields=["sales_start", "sales_end"]
        )

        availability = calculate_ticket_lot_availability(
            ticket_lot=self.ticket_lot
        )

        self.assertEqual(
            availability.status,
            TicketLotAvailabilityStatus.SCHEDULED,
        )

    def test_closed_lot_is_identified(self):
        self.ticket_lot.sales_start = (
            timezone.now() - timedelta(days=5)
        )
        self.ticket_lot.sales_end = (
            timezone.now() - timedelta(minutes=1)
        )
        self.ticket_lot.save(
            update_fields=["sales_start", "sales_end"]
        )

        availability = calculate_ticket_lot_availability(
            ticket_lot=self.ticket_lot
        )

        self.assertEqual(
            availability.status,
            TicketLotAvailabilityStatus.CLOSED,
        )

    def test_inactive_lot_and_ticket_type_are_identified(self):
        self.ticket_lot.is_active = False
        self.ticket_lot.save(update_fields=["is_active"])

        lot_availability = (
            calculate_ticket_lot_availability(
                ticket_lot=self.ticket_lot
            )
        )

        self.assertEqual(
            lot_availability.status,
            TicketLotAvailabilityStatus.INACTIVE_LOT,
        )

        self.ticket_lot.is_active = True
        self.ticket_lot.save(update_fields=["is_active"])

        self.ticket_type.is_active = False
        self.ticket_type.save(update_fields=["is_active"])

        type_availability = (
            calculate_ticket_lot_availability(
                ticket_lot=self.ticket_lot
            )
        )

        self.assertEqual(
            type_availability.status,
            (
                TicketLotAvailabilityStatus
                .INACTIVE_TICKET_TYPE
            ),
        )

    def test_event_and_organization_availability_are_checked(self):
        self.event.status = EventStatus.CANCELED
        self.event.save(update_fields=["status"])

        event_availability = (
            calculate_ticket_lot_availability(
                ticket_lot=self.ticket_lot
            )
        )

        self.assertEqual(
            event_availability.status,
            (
                TicketLotAvailabilityStatus
                .EVENT_UNAVAILABLE
            ),
        )

        self.event.status = EventStatus.PUBLISHED
        self.event.save(update_fields=["status"])

        self.organization.status = (
            OrganizationStatus.SUSPENDED
        )
        self.organization.save(update_fields=["status"])

        organization_availability = (
            calculate_ticket_lot_availability(
                ticket_lot=self.ticket_lot
            )
        )

        self.assertEqual(
            organization_availability.status,
            (
                TicketLotAvailabilityStatus
                .ORGANIZATION_UNAVAILABLE
            ),
        )

    def test_valid_reservation_quantity_is_accepted(self):
        availability = calculate_ticket_lot_availability(
            ticket_lot=self.ticket_lot
        )

        validated_quantity = validate_reservation_quantity(
            availability=availability,
            quantity=5,
        )

        self.assertEqual(validated_quantity, 5)

    def test_non_positive_or_invalid_quantity_is_rejected(self):
        availability = calculate_ticket_lot_availability(
            ticket_lot=self.ticket_lot
        )

        invalid_quantities = (
            0,
            -1,
            "2",
            True,
        )

        for quantity in invalid_quantities:
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValidationError):
                    validate_reservation_quantity(
                        availability=availability,
                        quantity=quantity,
                    )

    def test_quantity_above_availability_is_rejected(self):
        self.create_committed_item(
            quantity=7,
            status=OrderStatus.PAID,
        )

        availability = calculate_ticket_lot_availability(
            ticket_lot=self.ticket_lot
        )

        with self.assertRaises(ValidationError) as error:
            validate_reservation_quantity(
                availability=availability,
                quantity=4,
            )

        self.assertIn(
            "Restam 3 vaga(s)",
            str(error.exception),
        )

    def test_unavailable_lot_rejects_reservation(self):
        self.ticket_lot.sales_start = (
            timezone.now() + timedelta(days=1)
        )
        self.ticket_lot.sales_end = (
            timezone.now() + timedelta(days=5)
        )
        self.ticket_lot.save(
            update_fields=["sales_start", "sales_end"]
        )

        availability = calculate_ticket_lot_availability(
            ticket_lot=self.ticket_lot
        )

        with self.assertRaises(ValidationError):
            validate_reservation_quantity(
                availability=availability,
                quantity=1,
            )

    def test_locked_calculation_works_inside_transaction(self):
        with transaction.atomic():
            availability = (
                lock_ticket_lot_and_calculate_availability(
                    ticket_lot_id=self.ticket_lot.id,
                )
            )

        self.assertEqual(
            availability.ticket_lot.id,
            self.ticket_lot.id,
        )
        self.assertEqual(
            availability.available_quantity,
            10,
        )