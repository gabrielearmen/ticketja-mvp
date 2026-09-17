import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from PIL import Image

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.organizations.models import (
    Organization,
    OrganizationStatus,
)

from .models import (
    Event,
    EventStatus,
    SportCategory,
    TicketLot,
    TicketType,
)


TEST_MEDIA_ROOT = tempfile.mkdtemp(
    prefix="ticketja-public-event-test-media-"
)


def create_test_cover(filename="capa-publica.png"):
    """
    Cria uma imagem real e pequena exclusivamente para os testes.
    """
    image_buffer = BytesIO()

    image = Image.new(
        "RGB",
        (40, 25),
        color=(249, 115, 22),
    )
    image.save(image_buffer, format="PNG")
    image.close()

    image_buffer.seek(0)

    return SimpleUploadedFile(
        name=filename,
        content=image_buffer.read(),
        content_type="image/png",
    )


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class PublicEventDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.approved_organization = (
            Organization.objects.create(
                name="Organização Esportiva Aprovada",
                slug="organizacao-esportiva-aprovada",
                status=OrganizationStatus.APPROVED,
            )
        )

        cls.public_event = cls.create_event(
            organization=cls.approved_organization,
            title="Corrida Pública TicketJá",
            status=EventStatus.PUBLISHED,
        )

        cls.public_ticket_type = TicketType.objects.create(
            event=cls.public_event,
            name="Corrida 10 km",
            description="Participação na prova de 10 quilômetros.",
            capacity=100,
            is_active=True,
        )

        cls.current_lot = TicketLot.objects.create(
            ticket_type=cls.public_ticket_type,
            name="Primeiro lote",
            price=Decimal("89.90"),
            quantity=100,
            sales_start=timezone.now() - timedelta(hours=1),
            sales_end=timezone.now() + timedelta(days=10),
            is_active=True,
        )

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(
            TEST_MEDIA_ROOT,
            ignore_errors=True,
        )

    @classmethod
    def create_event(
        cls,
        *,
        organization,
        title,
        status,
        event_datetime=None,
    ):
        return Event.objects.create(
            organization=organization,
            title=title,
            summary=(
                "Evento esportivo criado para validar "
                "a experiência pública."
            ),
            sport_category=SportCategory.RUNNING,
            event_datetime=(
                event_datetime
                or timezone.now() + timedelta(days=30)
            ),
            city="Fortaleza",
            state="CE",
            address="Avenida Beira Mar, 1000",
            capacity=500,
            status=status,
            cover_image=create_test_cover(),
        )

    def public_detail_url(self, event):
        return reverse(
            "events:public-detail",
            kwargs={"event_id": event.id},
        )

    def test_published_event_detail_displays_public_information(self):
        response = self.client.get(
            self.public_detail_url(self.public_event)
        )

        self.assertEqual(response.status_code, 200)

        self.assertTemplateUsed(
            response,
            "events/public/event_detail.html",
        )

        self.assertContains(
            response,
            "Corrida Pública TicketJá",
        )
        self.assertContains(
            response,
            "Organização Esportiva Aprovada",
        )
        self.assertContains(
            response,
            "Corrida 10 km",
        )
        self.assertContains(
            response,
            "Primeiro lote",
        )
        self.assertContains(
            response,
            "Inscrever-se",
        )
        self.assertContains(
            response,
            self.public_event.cover_image.url,
        )

        self.assertTrue(
            response.context["has_open_sales"]
        )

        offers = response.context["ticket_offers"]

        self.assertEqual(len(offers), 1)
        self.assertEqual(
            offers[0]["sales_state"],
            "open",
        )
        self.assertEqual(
            offers[0]["lot"].price,
            Decimal("89.90"),
        )

    def test_draft_event_returns_404(self):
        draft_event = self.create_event(
            organization=self.approved_organization,
            title="Evento em Rascunho Privado",
            status=EventStatus.DRAFT,
        )

        response = self.client.get(
            self.public_detail_url(draft_event)
        )

        self.assertEqual(response.status_code, 404)

    def test_canceled_event_returns_404(self):
        canceled_event = self.create_event(
            organization=self.approved_organization,
            title="Evento Cancelado Privado",
            status=EventStatus.CANCELED,
        )

        response = self.client.get(
            self.public_detail_url(canceled_event)
        )

        self.assertEqual(response.status_code, 404)

    def test_past_event_returns_404(self):
        past_event = self.create_event(
            organization=self.approved_organization,
            title="Evento Já Realizado",
            status=EventStatus.PUBLISHED,
            event_datetime=(
                timezone.now() - timedelta(days=1)
            ),
        )

        response = self.client.get(
            self.public_detail_url(past_event)
        )

        self.assertEqual(response.status_code, 404)

    def test_events_from_non_approved_organizations_return_404(self):
        organization_scenarios = (
            (
                OrganizationStatus.PENDING,
                "organizacao-pendente",
                "Evento de Organização Pendente",
            ),
            (
                OrganizationStatus.SUSPENDED,
                "organizacao-suspensa",
                "Evento de Organização Suspensa",
            ),
        )

        for status, slug, event_title in organization_scenarios:
            with self.subTest(organization_status=status):
                organization = Organization.objects.create(
                    name=event_title,
                    slug=slug,
                    status=status,
                )

                event = self.create_event(
                    organization=organization,
                    title=event_title,
                    status=EventStatus.PUBLISHED,
                )

                response = self.client.get(
                    self.public_detail_url(event)
                )

                self.assertEqual(response.status_code, 404)

    def test_landing_page_excludes_non_public_events(self):
        draft_event = self.create_event(
            organization=self.approved_organization,
            title="Rascunho Não Exibido",
            status=EventStatus.DRAFT,
        )

        canceled_event = self.create_event(
            organization=self.approved_organization,
            title="Cancelado Não Exibido",
            status=EventStatus.CANCELED,
        )

        past_event = self.create_event(
            organization=self.approved_organization,
            title="Passado Não Exibido",
            status=EventStatus.PUBLISHED,
            event_datetime=(
                timezone.now() - timedelta(days=2)
            ),
        )

        pending_organization = Organization.objects.create(
            name="Organização Pendente da Landing",
            slug="organizacao-pendente-landing",
            status=OrganizationStatus.PENDING,
        )

        pending_organization_event = self.create_event(
            organization=pending_organization,
            title="Organização Pendente Não Exibida",
            status=EventStatus.PUBLISHED,
        )

        response = self.client.get(
            reverse("core:home")
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            self.public_event.title,
        )

        hidden_events = (
            draft_event,
            canceled_event,
            past_event,
            pending_organization_event,
        )

        for event in hidden_events:
            with self.subTest(event=event.title):
                self.assertNotContains(
                    response,
                    event.title,
                )

    def test_landing_page_card_links_to_public_detail(self):
        response = self.client.get(
            reverse("core:home")
        )

        detail_url = self.public_detail_url(
            self.public_event
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, detail_url)

    def test_page_identifies_open_scheduled_and_closed_lots(self):
        scheduled_type = TicketType.objects.create(
            event=self.public_event,
            name="Corrida 5 km",
            description="Participação na prova de 5 quilômetros.",
            capacity=100,
            is_active=True,
        )

        TicketLot.objects.create(
            ticket_type=scheduled_type,
            name="Lote programado",
            price=Decimal("59.90"),
            quantity=100,
            sales_start=timezone.now() + timedelta(days=11),
            sales_end=timezone.now() + timedelta(days=15),
            is_active=True,
        )

        closed_type = TicketType.objects.create(
            event=self.public_event,
            name="Caminhada",
            description="Participação na caminhada.",
            capacity=100,
            is_active=True,
        )

        TicketLot.objects.create(
            ticket_type=closed_type,
            name="Lote encerrado",
            price=Decimal("39.90"),
            quantity=100,
            sales_start=timezone.now() - timedelta(days=10),
            sales_end=timezone.now() - timedelta(days=2),
            is_active=True,
        )

        response = self.client.get(
            self.public_detail_url(self.public_event)
        )

        offers_by_name = {
            offer["ticket_type"].name: offer
            for offer in response.context["ticket_offers"]
        }

        self.assertEqual(
            offers_by_name["Corrida 10 km"]["sales_state"],
            "open",
        )
        self.assertEqual(
            offers_by_name["Corrida 5 km"]["sales_state"],
            "scheduled",
        )
        self.assertEqual(
            offers_by_name["Caminhada"]["sales_state"],
            "closed",
        )

        self.assertContains(response, "Em venda")
        self.assertContains(response, "Vendas programadas")
        self.assertContains(response, "Vendas encerradas")

    def test_inactive_ticket_types_and_lots_are_not_offered(self):
        inactive_type = TicketType.objects.create(
            event=self.public_event,
            name="Ingresso Inativo Oculto",
            description="Este ingresso não deve aparecer.",
            capacity=50,
            is_active=False,
        )

        TicketLot.objects.create(
            ticket_type=inactive_type,
            name="Lote do Ingresso Inativo",
            price=Decimal("10.00"),
            quantity=50,
            sales_start=timezone.now() - timedelta(hours=1),
            sales_end=timezone.now() + timedelta(days=5),
            is_active=True,
        )

        type_with_inactive_lot = TicketType.objects.create(
            event=self.public_event,
            name="Ingresso sem Lote Ativo",
            description="Tipo ativo, mas lote inativo.",
            capacity=50,
            is_active=True,
        )

        TicketLot.objects.create(
            ticket_type=type_with_inactive_lot,
            name="Lote Inativo Oculto",
            price=Decimal("20.00"),
            quantity=50,
            sales_start=timezone.now() - timedelta(hours=1),
            sales_end=timezone.now() + timedelta(days=5),
            is_active=False,
        )

        response = self.client.get(
            self.public_detail_url(self.public_event)
        )

        self.assertEqual(response.status_code, 200)

        self.assertNotContains(
            response,
            "Ingresso Inativo Oculto",
        )
        self.assertNotContains(
            response,
            "Lote do Ingresso Inativo",
        )
        self.assertNotContains(
            response,
            "Lote Inativo Oculto",
        )

        self.assertContains(
            response,
            "Ingresso sem Lote Ativo",
        )
        self.assertContains(
            response,
            "Nenhum lote ativo para este tipo",
        )