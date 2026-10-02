from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.events.models import (
    Event,
    EventStatus,
    SportCategory,
    TicketType,
)
from apps.organizations.models import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)

from .models import EventKit, KitOption, TicketTypeKit


class KitManagementViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.password = "Senha-Segura!2026"

        cls.organizer_a = user_model.objects.create_user(
            email="kits-organizador-a@example.com",
            password=cls.password,
            first_name="Organizador",
            last_name="A",
        )
        cls.organizer_b = user_model.objects.create_user(
            email="kits-organizador-b@example.com",
            password=cls.password,
            first_name="Organizador",
            last_name="B",
        )
        cls.buyer = user_model.objects.create_user(
            email="kits-comprador@example.com",
            password=cls.password,
            first_name="Comprador",
        )

        cls.organization_a = Organization.objects.create(
            name="Organização de Kits A",
            slug="organizacao-kits-view-a",
            status=OrganizationStatus.APPROVED,
        )
        cls.organization_b = Organization.objects.create(
            name="Organização de Kits B",
            slug="organizacao-kits-view-b",
            status=OrganizationStatus.APPROVED,
        )

        OrganizationMembership.objects.create(
            organization=cls.organization_a,
            user=cls.organizer_a,
            role=MembershipRole.OWNER,
            is_active=True,
        )
        OrganizationMembership.objects.create(
            organization=cls.organization_b,
            user=cls.organizer_b,
            role=MembershipRole.OWNER,
            is_active=True,
        )

        cls.event_a = cls.create_event(
            organization=cls.organization_a,
            title="Evento Kits View A",
        )
        cls.event_b = cls.create_event(
            organization=cls.organization_b,
            title="Evento Kits View B",
        )
        cls.published_event = cls.create_event(
            organization=cls.organization_a,
            title="Evento Kits Publicado",
            status=EventStatus.PUBLISHED,
        )

        cls.ticket_type_a = TicketType.objects.create(
            event=cls.event_a,
            name="Ingresso 5 km",
            description="Ingresso da organização A.",
            capacity=200,
            is_active=True,
        )
        cls.ticket_type_a_10k = TicketType.objects.create(
            event=cls.event_a,
            name="Ingresso 10 km",
            description="Segundo ingresso da organização A.",
            capacity=200,
            is_active=True,
        )
        cls.ticket_type_b = TicketType.objects.create(
            event=cls.event_b,
            name="Ingresso da organização B",
            description="Ingresso de outra organização.",
            capacity=200,
            is_active=True,
        )
        cls.published_ticket_type = TicketType.objects.create(
            event=cls.published_event,
            name="Ingresso publicado",
            description="Ingresso de evento publicado.",
            capacity=200,
            is_active=True,
        )

        cls.kit_a = EventKit.objects.create(
            event=cls.event_a,
            name="Kit da Organização A",
            description="Camiseta e número de peito.",
            is_required=True,
            is_active=True,
        )
        cls.kit_b = EventKit.objects.create(
            event=cls.event_b,
            name="Kit da Organização B",
            description="Kit que não pode ser acessado pela A.",
            is_required=True,
            is_active=True,
        )
        cls.published_kit = EventKit.objects.create(
            event=cls.published_event,
            name="Kit publicado",
            description="Kit disponível somente para consulta.",
            is_required=True,
            is_active=True,
        )

        TicketTypeKit.objects.create(
            kit=cls.kit_a,
            ticket_type=cls.ticket_type_a,
        )
        TicketTypeKit.objects.create(
            kit=cls.kit_b,
            ticket_type=cls.ticket_type_b,
        )
        TicketTypeKit.objects.create(
            kit=cls.published_kit,
            ticket_type=cls.published_ticket_type,
        )

        cls.option_a = KitOption.objects.create(
            kit=cls.kit_a,
            name="M",
            stock_quantity=40,
            is_active=True,
        )
        cls.option_b = KitOption.objects.create(
            kit=cls.kit_b,
            name="G",
            stock_quantity=30,
            is_active=True,
        )

    @classmethod
    def create_event(
        cls,
        *,
        organization,
        title,
        status=EventStatus.DRAFT,
    ):
        return Event.objects.create(
            organization=organization,
            title=title,
            summary="Evento utilizado nos testes das páginas de kits.",
            sport_category=SportCategory.RUNNING,
            event_datetime=timezone.now() + timedelta(days=30),
            city="Fortaleza",
            state="CE",
            address="Avenida de Teste, 100",
            capacity=500,
            status=status,
        )

    def login_as_organizer_a(self):
        self.client.force_login(self.organizer_a)

    def valid_kit_data(self, **changes):
        data = {
            "name": "Novo kit",
            "description": "Camiseta, número e medalha.",
            "is_required": "on",
            "is_active": "on",
            "ticket_types": [str(self.ticket_type_a.id)],
        }
        data.update(changes)
        return data

    def valid_option_data(self, **changes):
        data = {
            "name": "GG",
            "stock_quantity": 25,
            "is_active": "on",
        }
        data.update(changes)
        return data

    def test_unauthenticated_user_is_redirected_to_login(self):
        response = self.client.get(
            reverse(
                "kits:configuration",
                kwargs={"event_id": self.event_a.id},
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse("accounts:login"),
            response.url,
        )

    def test_buyer_without_organization_receives_403(self):
        self.client.force_login(self.buyer)

        response = self.client.get(
            reverse(
                "kits:configuration",
                kwargs={"event_id": self.event_a.id},
            )
        )

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(
            response,
            "organizations/no_access.html",
        )

    def test_list_shows_only_kits_from_requested_event(self):
        self.login_as_organizer_a()

        response = self.client.get(
            reverse(
                "kits:configuration",
                kwargs={"event_id": self.event_a.id},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.kit_a.name)
        self.assertNotContains(response, self.kit_b.name)

    def test_foreign_event_returns_404(self):
        self.login_as_organizer_a()

        response = self.client.get(
            reverse(
                "kits:configuration",
                kwargs={"event_id": self.event_b.id},
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_organizer_can_create_kit(self):
        self.login_as_organizer_a()

        response = self.client.post(
            reverse(
                "kits:create",
                kwargs={"event_id": self.event_a.id},
            ),
            data=self.valid_kit_data(),
        )

        self.assertRedirects(
            response,
            reverse(
                "kits:configuration",
                kwargs={"event_id": self.event_a.id},
            ),
        )

        kit = EventKit.objects.get(
            event=self.event_a,
            name="Novo kit",
        )

        self.assertTrue(kit.is_required)
        self.assertTrue(kit.is_active)
        self.assertTrue(
            kit.ticket_types.filter(
                id=self.ticket_type_a.id
            ).exists()
        )

    def test_foreign_ticket_type_is_rejected_by_form(self):
        self.login_as_organizer_a()

        response = self.client.post(
            reverse(
                "kits:create",
                kwargs={"event_id": self.event_a.id},
            ),
            data=self.valid_kit_data(
                name="Kit inválido",
                ticket_types=[str(self.ticket_type_b.id)],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "não pertence a este evento",
        )
        self.assertFalse(
            EventKit.objects.filter(
                event=self.event_a,
                name="Kit inválido",
            ).exists()
        )

    def test_foreign_kit_cannot_be_edited(self):
        self.login_as_organizer_a()

        response = self.client.get(
            reverse(
                "kits:update",
                kwargs={
                    "event_id": self.event_a.id,
                    "kit_id": self.kit_b.id,
                },
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_organizer_can_update_kit_and_links(self):
        self.login_as_organizer_a()

        response = self.client.post(
            reverse(
                "kits:update",
                kwargs={
                    "event_id": self.event_a.id,
                    "kit_id": self.kit_a.id,
                },
            ),
            data=self.valid_kit_data(
                name="Kit A atualizado",
                ticket_types=[
                    str(self.ticket_type_a_10k.id)
                ],
            ),
        )

        self.assertRedirects(
            response,
            reverse(
                "kits:configuration",
                kwargs={"event_id": self.event_a.id},
            ),
        )

        self.kit_a.refresh_from_db()

        self.assertEqual(
            self.kit_a.name,
            "Kit A atualizado",
        )
        self.assertSetEqual(
            set(self.kit_a.ticket_types.all()),
            {self.ticket_type_a_10k},
        )

    def test_organizer_can_create_option(self):
        self.login_as_organizer_a()

        response = self.client.post(
            reverse(
                "kits:option-create",
                kwargs={
                    "event_id": self.event_a.id,
                    "kit_id": self.kit_a.id,
                },
            ),
            data=self.valid_option_data(name="P"),
        )

        self.assertRedirects(
            response,
            reverse(
                "kits:configuration",
                kwargs={"event_id": self.event_a.id},
            ),
        )
        self.assertTrue(
            KitOption.objects.filter(
                kit=self.kit_a,
                name="P",
                stock_quantity=25,
            ).exists()
        )

    def test_organizer_can_update_option(self):
        self.login_as_organizer_a()

        response = self.client.post(
            reverse(
                "kits:option-update",
                kwargs={
                    "event_id": self.event_a.id,
                    "kit_id": self.kit_a.id,
                    "option_id": self.option_a.id,
                },
            ),
            data=self.valid_option_data(
                name="M atualizada",
                stock_quantity=55,
            ),
        )

        self.assertRedirects(
            response,
            reverse(
                "kits:configuration",
                kwargs={"event_id": self.event_a.id},
            ),
        )

        self.option_a.refresh_from_db()

        self.assertEqual(self.option_a.name, "M atualizada")
        self.assertEqual(self.option_a.stock_quantity, 55)

    def test_foreign_option_cannot_be_updated(self):
        self.login_as_organizer_a()

        response = self.client.get(
            reverse(
                "kits:option-update",
                kwargs={
                    "event_id": self.event_a.id,
                    "kit_id": self.kit_a.id,
                    "option_id": self.option_b.id,
                },
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_published_event_is_read_only(self):
        self.login_as_organizer_a()

        list_response = self.client.get(
            reverse(
                "kits:configuration",
                kwargs={"event_id": self.published_event.id},
            )
        )
        create_response = self.client.get(
            reverse(
                "kits:create",
                kwargs={"event_id": self.published_event.id},
            )
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(
            list_response,
            "somente para consulta",
        )
        self.assertEqual(create_response.status_code, 404)

    def test_stock_board_exposes_current_quantities(self):
        self.login_as_organizer_a()

        response = self.client.get(
            reverse(
                "kits:configuration",
                kwargs={"event_id": self.event_a.id},
            )
        )

        self.assertEqual(response.status_code, 200)

        kit_row = response.context["kit_rows"][0]
        option_row = kit_row["option_rows"][0]

        self.assertEqual(option_row.reserved_quantity, 0)
        self.assertEqual(option_row.available_quantity, 40)
        self.assertContains(response, "Estoque total")
        self.assertContains(response, "Disponível")

    def test_event_list_contains_kit_navigation(self):
        self.login_as_organizer_a()

        response = self.client.get(
            reverse("events:organizer-list")
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "kits:configuration",
                kwargs={"event_id": self.event_a.id},
            ),
        )

    def test_ticket_configuration_contains_kit_navigation(
        self,
    ):
        self.login_as_organizer_a()

        response = self.client.get(
            reverse(
                "events:ticket-configuration",
                kwargs={"event_id": self.event_a.id},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "kits:configuration",
                kwargs={"event_id": self.event_a.id},
            ),
        )