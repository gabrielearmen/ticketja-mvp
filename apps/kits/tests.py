from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from apps.events.models import (
    Event,
    EventStatus,
    SportCategory,
    TicketType,
)
from apps.organizations.models import (
    Organization,
    OrganizationStatus,
)

from .models import (
    EventKit,
    KitOption,
    TicketTypeKit,
)


class KitModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization_a = Organization.objects.create(
            name="Organização Kits A",
            slug="organizacao-kits-a",
            status=OrganizationStatus.APPROVED,
        )

        cls.organization_b = Organization.objects.create(
            name="Organização Kits B",
            slug="organizacao-kits-b",
            status=OrganizationStatus.APPROVED,
        )

        cls.event_a = cls.create_event(
            organization=cls.organization_a,
            title="Evento Kits A",
        )

        cls.event_b = cls.create_event(
            organization=cls.organization_b,
            title="Evento Kits B",
        )

        cls.ticket_type_a = TicketType.objects.create(
            event=cls.event_a,
            name="Corrida 5 km",
            description="Ingresso A",
            capacity=100,
            is_active=True,
        )

        cls.ticket_type_b = TicketType.objects.create(
            event=cls.event_b,
            name="Corrida 10 km",
            description="Ingresso B",
            capacity=100,
            is_active=True,
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
            summary="Evento utilizado nos testes de kits.",
            sport_category=SportCategory.RUNNING,
            event_datetime=(
                timezone.now() + timedelta(days=30)
            ),
            city="Fortaleza",
            state="CE",
            address="Avenida de Teste, 100",
            capacity=200,
            status=EventStatus.DRAFT,
        )

    def create_kit(self, **changes):
        data = {
            "event": self.event_a,
            "name": "Kit do Atleta",
            "description": "Camiseta e número de peito.",
            "is_required": True,
            "is_active": True,
        }

        data.update(changes)

        return EventKit.objects.create(**data)

    def test_valid_kit_structure(self):
        kit = self.create_kit()

        option = KitOption.objects.create(
            kit=kit,
            name="M",
            stock_quantity=50,
            is_active=True,
        )

        assignment = TicketTypeKit(
            kit=kit,
            ticket_type=self.ticket_type_a,
        )

        assignment.full_clean()
        assignment.save()

        self.assertEqual(option.kit, kit)

        self.assertQuerySetEqual(
            kit.ticket_types.all(),
            [self.ticket_type_a],
        )

    def test_kit_name_is_unique_per_event_ignoring_case(self):
        self.create_kit(name="Kit Premium")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_kit(name="KIT PREMIUM")

    def test_same_kit_name_is_allowed_in_another_event(self):
        self.create_kit(name="Kit Geral")

        other_kit = self.create_kit(
            event=self.event_b,
            name="KIT GERAL",
        )

        self.assertEqual(
            other_kit.event,
            self.event_b,
        )

    def test_option_requires_positive_stock(self):
        kit = self.create_kit()

        option = KitOption(
            kit=kit,
            name="P",
            stock_quantity=0,
        )

        with self.assertRaises(ValidationError):
            option.full_clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                KitOption.objects.create(
                    kit=kit,
                    name="P",
                    stock_quantity=0,
                )

    def test_option_name_is_unique_per_kit_ignoring_case(
        self,
    ):
        kit = self.create_kit()

        KitOption.objects.create(
            kit=kit,
            name="GG",
            stock_quantity=10,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                KitOption.objects.create(
                    kit=kit,
                    name="gg",
                    stock_quantity=10,
                )

    def test_assignment_rejects_different_event(self):
        kit = self.create_kit()

        assignment = TicketTypeKit(
            kit=kit,
            ticket_type=self.ticket_type_b,
        )

        with self.assertRaises(ValidationError):
            assignment.full_clean()

    def test_same_assignment_cannot_be_duplicated(self):
        kit = self.create_kit()

        TicketTypeKit.objects.create(
            kit=kit,
            ticket_type=self.ticket_type_a,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TicketTypeKit.objects.create(
                    kit=kit,
                    ticket_type=self.ticket_type_a,
                )

    def test_event_with_kit_cannot_be_deleted(self):
        self.create_kit()

        with self.assertRaises(ProtectedError):
            self.event_a.delete()

    def test_kit_with_options_cannot_be_deleted(self):
        kit = self.create_kit()

        KitOption.objects.create(
            kit=kit,
            name="Sem tamanho",
            stock_quantity=100,
        )

        with self.assertRaises(ProtectedError):
            kit.delete()