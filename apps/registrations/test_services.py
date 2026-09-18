from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
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

from .models import Registration
from .services import ensure_registration_slots


class RegistrationSlotsServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.buyer_a = user_model.objects.create_user(
            email="comprador-a@example.com",
            password="senha-forte-123",
        )

        cls.buyer_b = user_model.objects.create_user(
            email="comprador-b@example.com",
            password="senha-forte-123",
        )

        cls.organization_a = Organization.objects.create(
            name="Organização A",
            slug="organizacao-a-registration-tests",
            status=OrganizationStatus.APPROVED,
        )

        cls.organization_b = Organization.objects.create(
            name="Organização B",
            slug="organizacao-b-registration-tests",
            status=OrganizationStatus.APPROVED,
        )

        cls.now = timezone.now()

        cls.event_a = cls.create_event(
            organization=cls.organization_a,
            title="Evento A",
        )

        cls.event_b = cls.create_event(
            organization=cls.organization_b,
            title="Evento B",
        )

        cls.order_a, cls.order_item_a = (
            cls.create_order_with_item(
                buyer=cls.buyer_a,
                organization=cls.organization_a,
                event=cls.event_a,
                quantity=3,
                suffix="a",
            )
        )

        cls.order_b, cls.order_item_b = (
            cls.create_order_with_item(
                buyer=cls.buyer_b,
                organization=cls.organization_b,
                event=cls.event_b,
                quantity=2,
                suffix="b",
            )
        )

    @classmethod
    def create_event(
        cls,
        *,
        organization,
        title,
    ):
        return Event.objects.create(
            organization=organization,
            title=title,
            summary="Evento utilizado nos testes.",
            sport_category=SportCategory.RUNNING,
            event_datetime=(
                cls.now + timedelta(days=30)
            ),
            city="Fortaleza",
            state="CE",
            address="Avenida de Teste, 100",
            capacity=100,
            status=EventStatus.PUBLISHED,
            cover_image="events/covers/teste.png",
        )

    @classmethod
    def create_order_with_item(
        cls,
        *,
        buyer,
        organization,
        event,
        quantity,
        suffix,
    ):
        ticket_type = TicketType.objects.create(
            event=event,
            name=f"Ingresso {suffix}",
            description="Ingresso de teste.",
            capacity=100,
            is_active=True,
        )

        ticket_lot = TicketLot.objects.create(
            ticket_type=ticket_type,
            name=f"Lote {suffix}",
            price=Decimal("50.00"),
            quantity=100,
            sales_start=(
                cls.now - timedelta(days=1)
            ),
            sales_end=(
                cls.now + timedelta(days=20)
            ),
            is_active=True,
        )

        subtotal = (
            Decimal("50.00") * quantity
        )

        order = Order.objects.create(
            buyer=buyer,
            organization=organization,
            event=event,
            status=OrderStatus.AWAITING_PAYMENT,
            subtotal=subtotal,
            service_fee=Decimal("0.00"),
            total=subtotal,
            reservation_expires_at=(
                cls.now + timedelta(minutes=15)
            ),
        )

        order_item = OrderItem.objects.create(
            order=order,
            ticket_type=ticket_type,
            ticket_lot=ticket_lot,
            quantity=quantity,
            unit_price=Decimal("50.00"),
            subtotal=subtotal,
        )

        return order, order_item

    def test_creates_one_registration_per_ticket(self):
        result = ensure_registration_slots(
            order_id=self.order_a.id,
            buyer=self.buyer_a,
            at=self.now,
        )

        self.assertEqual(result.created_count, 3)
        self.assertEqual(len(result.registrations), 3)

        self.assertEqual(
            [
                registration.position
                for registration in result.registrations
            ],
            [1, 2, 3],
        )

        self.assertTrue(
            all(
                registration.order_item_id
                == self.order_item_a.id
                for registration in result.registrations
            )
        )

    def test_repeated_execution_is_idempotent(self):
        first_result = ensure_registration_slots(
            order_id=self.order_a.id,
            buyer=self.buyer_a,
            at=self.now,
        )

        first_ids = {
            registration.id
            for registration in first_result.registrations
        }

        second_result = ensure_registration_slots(
            order_id=self.order_a.id,
            buyer=self.buyer_a,
            at=self.now,
        )

        second_ids = {
            registration.id
            for registration in second_result.registrations
        }

        self.assertEqual(second_result.created_count, 0)
        self.assertEqual(first_ids, second_ids)
        self.assertEqual(
            Registration.objects.filter(
                order_item=self.order_item_a
            ).count(),
            3,
        )

    def test_preserves_existing_registration(self):
        existing_registration = (
            Registration.objects.create(
                order_item=self.order_item_a,
                position=1,
            )
        )

        result = ensure_registration_slots(
            order_id=self.order_a.id,
            buyer=self.buyer_a,
            at=self.now,
        )

        self.assertEqual(result.created_count, 2)

        persisted_registration = (
            Registration.objects.get(
                order_item=self.order_item_a,
                position=1,
            )
        )

        self.assertEqual(
            persisted_registration.id,
            existing_registration.id,
        )

    def test_rejects_registration_above_quantity(self):
        Registration.objects.create(
            order_item=self.order_item_a,
            position=4,
        )

        with self.assertRaises(ValidationError) as context:
            ensure_registration_slots(
                order_id=self.order_a.id,
                buyer=self.buyer_a,
                at=self.now,
            )

        self.assertIn(
            "order",
            context.exception.message_dict,
        )

        self.assertEqual(
            Registration.objects.filter(
                order_item=self.order_item_a
            ).count(),
            1,
        )

    def test_buyer_cannot_access_another_order(self):
        with self.assertRaises(ValidationError) as context:
            ensure_registration_slots(
                order_id=self.order_b.id,
                buyer=self.buyer_a,
                at=self.now,
            )

        self.assertEqual(
            context.exception.message_dict["order"],
            ["Pedido indisponível para esta operação."],
        )

        self.assertFalse(
            Registration.objects.filter(
                order_item=self.order_item_b
            ).exists()
        )

    def test_organization_data_remains_isolated(self):
        ensure_registration_slots(
            order_id=self.order_a.id,
            buyer=self.buyer_a,
            at=self.now,
        )

        self.assertEqual(
            Registration.objects.filter(
                order_item__order__organization=(
                    self.organization_a
                )
            ).count(),
            3,
        )

        self.assertEqual(
            Registration.objects.filter(
                order_item__order__organization=(
                    self.organization_b
                )
            ).count(),
            0,
        )

    def test_expired_reservation_is_rejected(self):
        self.order_a.reservation_expires_at = self.now
        self.order_a.save(
            update_fields=(
                "reservation_expires_at",
                "updated_at",
            )
        )

        with self.assertRaises(ValidationError) as context:
            ensure_registration_slots(
                order_id=self.order_a.id,
                buyer=self.buyer_a,
                at=self.now,
            )

        self.assertIn(
            "prazo da reserva terminou",
            context.exception.message_dict["order"][0],
        )

        self.assertFalse(
            Registration.objects.filter(
                order_item=self.order_item_a
            ).exists()
        )

    def test_existing_data_is_preserved_after_expiration(self):
        existing_registration = (
            Registration.objects.create(
                order_item=self.order_item_a,
                position=1,
                full_name="Participante Existente",
            )
        )

        self.order_a.reservation_expires_at = self.now
        self.order_a.save(
            update_fields=(
                "reservation_expires_at",
                "updated_at",
            )
        )

        with self.assertRaises(ValidationError):
            ensure_registration_slots(
                order_id=self.order_a.id,
                buyer=self.buyer_a,
                at=self.now,
            )

        existing_registration.refresh_from_db()

        self.assertEqual(
            existing_registration.full_name,
            "Participante Existente",
        )

        self.assertEqual(
            Registration.objects.filter(
                order_item=self.order_item_a
            ).count(),
            1,
        )

    def test_non_waiting_order_is_rejected(self):
        self.order_a.status = OrderStatus.CANCELED
        self.order_a.save(
            update_fields=(
                "status",
                "updated_at",
            )
        )

        with self.assertRaises(ValidationError) as context:
            ensure_registration_slots(
                order_id=self.order_a.id,
                buyer=self.buyer_a,
                at=self.now,
            )

        self.assertIn(
            "aguardando pagamento",
            context.exception.message_dict["order"][0],
        )

    def test_inactive_buyer_is_rejected(self):
        self.buyer_a.is_active = False
        self.buyer_a.save(update_fields=("is_active",))

        with self.assertRaises(ValidationError) as context:
            ensure_registration_slots(
                order_id=self.order_a.id,
                buyer=self.buyer_a,
                at=self.now,
            )

        self.assertIn(
            "buyer",
            context.exception.message_dict,
        )