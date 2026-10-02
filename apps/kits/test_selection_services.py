from datetime import date, timedelta
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
from apps.registrations.models import Registration
from apps.registrations.services import (
    ensure_registration_slots,
    update_registration_participants,
)

from .models import (
    EventKit,
    KitOption,
    RegistrationKitSelection,
    TicketTypeKit,
)
from .selectors import option_availabilities_for_kit


class RegistrationKitSelectionServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.buyer = user_model.objects.create_user(
            email="comprador-kits@example.com",
            password="senha-forte-2026",
        )

        cls.organization = Organization.objects.create(
            name="Organização Escolhas de Kits",
            slug="organizacao-escolhas-kits",
            status=OrganizationStatus.APPROVED,
        )

        now = timezone.now()

        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Corrida com Kit",
            summary="Evento para escolhas individuais de kits.",
            sport_category=SportCategory.RUNNING,
            event_datetime=now + timedelta(days=30),
            city="Fortaleza",
            state="CE",
            address="Avenida da Corrida, 100",
            capacity=100,
            status=EventStatus.PUBLISHED,
            cover_image="events/covers/kit.png",
        )

        cls.ticket_type = TicketType.objects.create(
            event=cls.event,
            name="Corrida 5 km",
            description="Ingresso com kit.",
            capacity=100,
            is_active=True,
        )

        cls.ticket_lot = TicketLot.objects.create(
            ticket_type=cls.ticket_type,
            name="Primeiro lote",
            price=Decimal("60.00"),
            quantity=100,
            sales_start=now - timedelta(days=1),
            sales_end=now + timedelta(days=20),
            is_active=True,
        )

        cls.kit = EventKit.objects.create(
            event=cls.event,
            name="Kit Camiseta",
            description="Camiseta oficial da corrida.",
            is_required=True,
            is_active=True,
        )

        TicketTypeKit.objects.create(
            kit=cls.kit,
            ticket_type=cls.ticket_type,
        )

        cls.option_m = KitOption.objects.create(
            kit=cls.kit,
            name="M",
            stock_quantity=1,
            is_active=True,
        )
        cls.option_g = KitOption.objects.create(
            kit=cls.kit,
            name="G",
            stock_quantity=2,
            is_active=True,
        )

        cls.order = Order.objects.create(
            buyer=cls.buyer,
            organization=cls.organization,
            event=cls.event,
            status=OrderStatus.AWAITING_PAYMENT,
            subtotal=Decimal("120.00"),
            service_fee=Decimal("0.00"),
            total=Decimal("120.00"),
            reservation_expires_at=(
                now + timedelta(minutes=15)
            ),
        )

        cls.order_item = OrderItem.objects.create(
            order=cls.order,
            ticket_type=cls.ticket_type,
            ticket_lot=cls.ticket_lot,
            quantity=2,
            unit_price=Decimal("60.00"),
            subtotal=Decimal("120.00"),
        )

    def registrations(self):
        ensure_registration_slots(
            order_id=self.order.id,
            buyer=self.buyer,
        )

        return list(
            Registration.objects
            .filter(order_item=self.order_item)
            .select_related(
                "order_item",
                "order_item__order",
                "order_item__ticket_type",
            )
            .order_by("position")
        )

    def participant_payload(self, choices):
        registrations = self.registrations()
        payload = []

        for registration in registrations:
            option = choices[registration.position]

            payload.append(
                {
                    "registration_id": registration.id,
                    "full_name": (
                        f"Participante "
                        f"{registration.position}"
                    ),
                    "document_type": "outro",
                    "document_number": (
                        f"DOC-{registration.position}"
                    ),
                    "birth_date": date(
                        1990,
                        1,
                        registration.position,
                    ),
                    "email": "",
                    "phone": "",
                    "emergency_contact_name": "",
                    "emergency_contact_phone": "",
                    "kit_selections": [
                        {
                            "kit_id": self.kit.id,
                            "option_id": (
                                option.id
                                if option is not None
                                else None
                            ),
                        }
                    ],
                }
            )

        return payload

    def save_choices(self, choices):
        return update_registration_participants(
            order_id=self.order.id,
            buyer=self.buyer,
            participants_data=(
                self.participant_payload(choices)
            ),
        )

    def test_each_participant_can_choose_own_option(self):
        self.save_choices(
            {
                1: self.option_m,
                2: self.option_g,
            }
        )

        registrations = self.registrations()

        first_selection = (
            registrations[0].kit_selections.get(
                kit=self.kit
            )
        )
        second_selection = (
            registrations[1].kit_selections.get(
                kit=self.kit
            )
        )

        self.assertEqual(
            first_selection.option,
            self.option_m,
        )
        self.assertEqual(
            second_selection.option,
            self.option_g,
        )

    def test_reprocessing_is_idempotent(self):
        choices = {
            1: self.option_m,
            2: self.option_g,
        }

        first_result = self.save_choices(choices)
        second_result = self.save_choices(choices)

        self.assertEqual(
            RegistrationKitSelection.objects.count(),
            2,
        )
        self.assertEqual(
            len(first_result.kit_selections),
            2,
        )
        self.assertEqual(
            len(second_result.kit_selections),
            2,
        )

    def test_required_kit_cannot_be_skipped(self):
        with self.assertRaises(ValidationError):
            self.save_choices(
                {
                    1: None,
                    2: self.option_g,
                }
            )

        self.assertFalse(
            RegistrationKitSelection.objects.exists()
        )
        self.assertFalse(
            Registration.objects.filter(
                completed_at__isnull=False,
            ).exists()
        )

    def test_option_from_another_kit_is_rejected(self):
        other_kit = EventKit.objects.create(
            event=self.event,
            name="Outro kit",
            description="Kit diferente.",
            is_required=False,
            is_active=True,
        )

        other_option = KitOption.objects.create(
            kit=other_kit,
            name="Única",
            stock_quantity=10,
            is_active=True,
        )

        with self.assertRaises(ValidationError):
            self.save_choices(
                {
                    1: other_option,
                    2: self.option_g,
                }
            )

        self.assertFalse(
            RegistrationKitSelection.objects.exists()
        )

    def test_stock_cannot_be_exceeded(self):
        with self.assertRaises(ValidationError):
            self.save_choices(
                {
                    1: self.option_m,
                    2: self.option_m,
                }
            )

        self.assertFalse(
            RegistrationKitSelection.objects.exists()
        )
        self.assertFalse(
            Registration.objects.filter(
                completed_at__isnull=False,
            ).exists()
        )

    def test_participant_can_change_option(self):
        self.save_choices(
            {
                1: self.option_m,
                2: self.option_g,
            }
        )

        self.save_choices(
            {
                1: self.option_g,
                2: self.option_g,
            }
        )

        selections = list(
            RegistrationKitSelection.objects
            .order_by("registration__position")
        )

        self.assertEqual(len(selections), 2)
        self.assertTrue(
            all(
                selection.option_id
                == self.option_g.id
                for selection in selections
            )
        )

    def test_valid_reservation_occupies_stock(self):
        self.save_choices(
            {
                1: self.option_m,
                2: self.option_g,
            }
        )

        availability = {
            row.option.id: row
            for row in option_availabilities_for_kit(
                kit=self.kit
            )
        }

        self.assertEqual(
            availability[
                self.option_m.id
            ].reserved_quantity,
            1,
        )
        self.assertEqual(
            availability[
                self.option_m.id
            ].available_quantity,
            0,
        )
        self.assertEqual(
            availability[
                self.option_g.id
            ].reserved_quantity,
            1,
        )

    def test_expired_order_releases_kit_stock(self):
        self.save_choices(
            {
                1: self.option_m,
                2: self.option_g,
            }
        )

        self.order.status = OrderStatus.EXPIRED
        self.order.reservation_expires_at = (
            timezone.now() - timedelta(seconds=1)
        )
        self.order.save(
            update_fields=(
                "status",
                "reservation_expires_at",
                "updated_at",
            )
        )

        availability = (
            option_availabilities_for_kit(
                kit=self.kit
            )
        )

        self.assertTrue(
            all(
                row.reserved_quantity == 0
                for row in availability
            )
        )

    def test_paid_order_keeps_kit_stock_committed(self):
        self.save_choices(
            {
                1: self.option_m,
                2: self.option_g,
            }
        )

        self.order.status = OrderStatus.PAID
        self.order.reservation_expires_at = (
            timezone.now() - timedelta(seconds=1)
        )
        self.order.save(
            update_fields=(
                "status",
                "reservation_expires_at",
                "updated_at",
            )
        )

        availability = {
            row.option.id: row
            for row in option_availabilities_for_kit(
                kit=self.kit
            )
        }

        self.assertEqual(
            availability[
                self.option_m.id
            ].reserved_quantity,
            1,
        )
        self.assertEqual(
            availability[
                self.option_g.id
            ].reserved_quantity,
            1,
        )

    def test_optional_kit_can_be_skipped(self):
        self.kit.is_required = False
        self.kit.save(
            update_fields=(
                "is_required",
                "updated_at",
            )
        )

        result = self.save_choices(
            {
                1: None,
                2: None,
            }
        )

        self.assertEqual(
            len(result.kit_selections),
            0,
        )
        self.assertFalse(
            RegistrationKitSelection.objects.exists()
        )
        self.assertEqual(
            Registration.objects.filter(
                completed_at__isnull=False,
            ).count(),
            2,
        )