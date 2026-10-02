from datetime import timedelta

from django.core.exceptions import ValidationError
from django.http import Http404
from django.test import TestCase
from django.utils import timezone

from apps.events.models import (
    Event,
    EventStatus,
    TicketType,
)
from apps.organizations.models import Organization

from .forms import EventKitForm
from .models import EventKit, KitOption
from .services import (
    create_event_kit,
    create_kit_option,
    update_event_kit,
    update_kit_option,
)


class KitManagementServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization_a = Organization.objects.create(
            name="Organização A",
            slug="organizacao-a",
            status="approved",
        )
        cls.organization_b = Organization.objects.create(
            name="Organização B",
            slug="organizacao-b",
            status="approved",
        )

        cls.event_a = Event.objects.create(
            organization=cls.organization_a,
            title="Corrida da Organização A",
            summary="Evento para os testes da gestão de kits.",
            sport_category="running",
            event_datetime=timezone.now() + timedelta(days=30),
            city="Fortaleza",
            state="CE",
            address="Avenida dos Esportes, 100",
            capacity=500,
            status=EventStatus.DRAFT,
        )
        cls.event_b = Event.objects.create(
            organization=cls.organization_b,
            title="Corrida da Organização B",
            summary="Evento pertencente a outra organização.",
            sport_category="running",
            event_datetime=timezone.now() + timedelta(days=35),
            city="Recife",
            state="PE",
            address="Rua da Corrida, 200",
            capacity=300,
            status=EventStatus.DRAFT,
        )
        cls.published_event = Event.objects.create(
            organization=cls.organization_a,
            title="Evento já publicado",
            summary="Evento que não aceita alteração estrutural.",
            sport_category="running",
            event_datetime=timezone.now() + timedelta(days=40),
            city="Natal",
            state="RN",
            address="Avenida Principal, 300",
            capacity=200,
            status=EventStatus.PUBLISHED,
        )

        cls.ticket_type_a_5k = TicketType.objects.create(
            event=cls.event_a,
            name="Corrida 5 km",
            description="Ingresso para a corrida de 5 km.",
            capacity=250,
            is_active=True,
        )
        cls.ticket_type_a_10k = TicketType.objects.create(
            event=cls.event_a,
            name="Corrida 10 km",
            description="Ingresso para a corrida de 10 km.",
            capacity=250,
            is_active=True,
        )
        cls.ticket_type_b = TicketType.objects.create(
            event=cls.event_b,
            name="Ingresso da Organização B",
            description="Não pode ser usado pela organização A.",
            capacity=200,
            is_active=True,
        )
        cls.published_ticket_type = TicketType.objects.create(
            event=cls.published_event,
            name="Ingresso publicado",
            description="Ingresso de evento publicado.",
            capacity=150,
            is_active=True,
        )

    def kit_data(self, *, ticket_types=None, **overrides):
        data = {
            "name": "Kit Corrida 5 km",
            "description": "Camiseta, número de peito e medalha.",
            "is_required": True,
            "is_active": True,
            "ticket_types": (
                ticket_types
                if ticket_types is not None
                else [self.ticket_type_a_5k]
            ),
        }
        data.update(overrides)
        return data

    def option_data(self, **overrides):
        data = {
            "name": "M",
            "stock_quantity": 80,
            "is_active": True,
        }
        data.update(overrides)
        return data

    def create_kit_a(self):
        return create_event_kit(
            organization=self.organization_a,
            event_id=self.event_a.id,
            cleaned_data=self.kit_data(),
        )

    def test_form_lists_only_ticket_types_from_its_event(self):
        form = EventKitForm(event=self.event_a)

        queryset = form.fields["ticket_types"].queryset

        self.assertIn(self.ticket_type_a_5k, queryset)
        self.assertIn(self.ticket_type_a_10k, queryset)
        self.assertNotIn(self.ticket_type_b, queryset)

    def test_create_kit_with_multiple_ticket_types(self):
        kit = create_event_kit(
            organization=self.organization_a,
            event_id=self.event_a.id,
            cleaned_data=self.kit_data(
                ticket_types=[
                    self.ticket_type_a_5k,
                    self.ticket_type_a_10k,
                ]
            ),
        )

        self.assertEqual(kit.event, self.event_a)
        self.assertTrue(kit.is_required)
        self.assertSetEqual(
            set(kit.ticket_types.all()),
            {
                self.ticket_type_a_5k,
                self.ticket_type_a_10k,
            },
        )

    def test_create_kit_rejects_ticket_type_from_another_event(self):
        with self.assertRaises(ValidationError):
            create_event_kit(
                organization=self.organization_a,
                event_id=self.event_a.id,
                cleaned_data=self.kit_data(
                    ticket_types=[self.ticket_type_b]
                ),
            )

        self.assertFalse(
            EventKit.objects.filter(event=self.event_a).exists()
        )

    def test_published_event_cannot_receive_new_kit(self):
        with self.assertRaises(Http404):
            create_event_kit(
                organization=self.organization_a,
                event_id=self.published_event.id,
                cleaned_data=self.kit_data(
                    ticket_types=[self.published_ticket_type]
                ),
            )

    def test_update_kit_replaces_ticket_type_links(self):
        kit = self.create_kit_a()

        updated_kit = update_event_kit(
            organization=self.organization_a,
            event_id=self.event_a.id,
            kit_id=kit.id,
            cleaned_data=self.kit_data(
                name="Kit Corrida Atualizado",
                ticket_types=[self.ticket_type_a_10k],
            ),
        )

        self.assertEqual(updated_kit.id, kit.id)
        self.assertEqual(
            updated_kit.name,
            "Kit Corrida Atualizado",
        )
        self.assertSetEqual(
            set(updated_kit.ticket_types.all()),
            {self.ticket_type_a_10k},
        )

    def test_other_organization_cannot_update_kit(self):
        kit = self.create_kit_a()

        with self.assertRaises(Http404):
            update_event_kit(
                organization=self.organization_b,
                event_id=self.event_a.id,
                kit_id=kit.id,
                cleaned_data=self.kit_data(),
            )

    def test_create_option_for_kit(self):
        kit = self.create_kit_a()

        option = create_kit_option(
            organization=self.organization_a,
            event_id=self.event_a.id,
            kit_id=kit.id,
            cleaned_data=self.option_data(),
        )

        self.assertEqual(option.kit, kit)
        self.assertEqual(option.name, "M")
        self.assertEqual(option.stock_quantity, 80)

    def test_other_organization_cannot_create_option(self):
        kit = self.create_kit_a()

        with self.assertRaises(Http404):
            create_kit_option(
                organization=self.organization_b,
                event_id=self.event_a.id,
                kit_id=kit.id,
                cleaned_data=self.option_data(),
            )

        self.assertFalse(
            KitOption.objects.filter(kit=kit).exists()
        )

    def test_option_cannot_be_updated_through_another_kit(self):
        first_kit = self.create_kit_a()

        second_kit = create_event_kit(
            organization=self.organization_a,
            event_id=self.event_a.id,
            cleaned_data=self.kit_data(
                name="Segundo kit",
                ticket_types=[self.ticket_type_a_10k],
            ),
        )

        option = create_kit_option(
            organization=self.organization_a,
            event_id=self.event_a.id,
            kit_id=first_kit.id,
            cleaned_data=self.option_data(),
        )

        with self.assertRaises(Http404):
            update_kit_option(
                organization=self.organization_a,
                event_id=self.event_a.id,
                kit_id=second_kit.id,
                option_id=option.id,
                cleaned_data=self.option_data(
                    stock_quantity=999
                ),
            )

        option.refresh_from_db()
        self.assertEqual(option.stock_quantity, 80)

    def test_published_event_blocks_option_update(self):
        published_kit = EventKit.objects.create(
            event=self.published_event,
            name="Kit publicado",
            description="Kit já publicado.",
            is_required=True,
            is_active=True,
        )
        option = KitOption.objects.create(
            kit=published_kit,
            name="G",
            stock_quantity=50,
            is_active=True,
        )

        with self.assertRaises(Http404):
            update_kit_option(
                organization=self.organization_a,
                event_id=self.published_event.id,
                kit_id=published_kit.id,
                option_id=option.id,
                cleaned_data=self.option_data(
                    name="GG",
                    stock_quantity=40,
                ),
            )

    def test_option_is_deactivated_without_being_deleted(self):
        kit = self.create_kit_a()

        option = create_kit_option(
            organization=self.organization_a,
            event_id=self.event_a.id,
            kit_id=kit.id,
            cleaned_data=self.option_data(),
        )

        update_kit_option(
            organization=self.organization_a,
            event_id=self.event_a.id,
            kit_id=kit.id,
            option_id=option.id,
            cleaned_data=self.option_data(
                is_active=False,
            ),
        )

        option.refresh_from_db()

        self.assertFalse(option.is_active)
        self.assertTrue(
            KitOption.objects.filter(id=option.id).exists()
        )