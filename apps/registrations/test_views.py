from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
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


class ParticipantDetailsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.buyer = user_model.objects.create_user(
            email="comprador-participantes@example.com",
            password="senha-forte-123",
        )

        cls.other_buyer = user_model.objects.create_user(
            email="outro-comprador@example.com",
            password="senha-forte-123",
        )

        cls.organization = Organization.objects.create(
            name="Organização Participantes",
            slug="organizacao-participantes",
            status=OrganizationStatus.APPROVED,
        )

        now = timezone.now()

        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Corrida Participantes",
            summary="Evento dos testes de participantes.",
            sport_category=SportCategory.RUNNING,
            event_datetime=now + timedelta(days=30),
            city="Fortaleza",
            state="CE",
            address="Avenida de Teste, 100",
            capacity=100,
            status=EventStatus.PUBLISHED,
            cover_image="events/covers/teste.png",
        )

        cls.ticket_type = TicketType.objects.create(
            event=cls.event,
            name="Corrida 5 km",
            description="Ingresso de teste.",
            capacity=100,
            is_active=True,
        )

        cls.ticket_lot = TicketLot.objects.create(
            ticket_type=cls.ticket_type,
            name="Primeiro lote",
            price=Decimal("50.00"),
            quantity=100,
            sales_start=now - timedelta(days=1),
            sales_end=now + timedelta(days=20),
            is_active=True,
        )

        cls.order = Order.objects.create(
            buyer=cls.buyer,
            organization=cls.organization,
            event=cls.event,
            status=OrderStatus.AWAITING_PAYMENT,
            subtotal=Decimal("100.00"),
            service_fee=Decimal("0.00"),
            total=Decimal("100.00"),
            reservation_expires_at=(
                now + timedelta(minutes=15)
            ),
        )

        cls.order_item = OrderItem.objects.create(
            order=cls.order,
            ticket_type=cls.ticket_type,
            ticket_lot=cls.ticket_lot,
            quantity=2,
            unit_price=Decimal("50.00"),
            subtotal=Decimal("100.00"),
        )

    def setUp(self):
        self.url = reverse(
            "registrations:participants",
            kwargs={
                "public_code": self.order.public_code,
            },
        )

    def registration_queryset(self):
        return (
            Registration.objects
            .filter(order_item=self.order_item)
            .order_by("position")
        )

    def valid_post_data(self):
        ensure_registration_slots(
            order_id=self.order.id,
            buyer=self.buyer,
        )

        registrations = list(
            self.registration_queryset()
        )

        data = {
            "participants-TOTAL_FORMS": "2",
            "participants-INITIAL_FORMS": "2",
            "participants-MIN_NUM_FORMS": "0",
            "participants-MAX_NUM_FORMS": "1000",
        }

        participants = (
            {
                "full_name": "Ana Participante",
                "document_type": "cpf",
                "document_number": "529.982.247-25",
                "birth_date": "1990-01-10",
                "email": "ANA@EXAMPLE.COM",
                "phone": "(85) 99999-9999",
                "emergency_contact_name": "",
                "emergency_contact_phone": "",
            },
            {
                "full_name": "Bruno Participante",
                "document_type": "passaporte",
                "document_number": "br 123456",
                "birth_date": "1988-02-20",
                "email": "",
                "phone": "",
                "emergency_contact_name": (
                    "Contato de Emergência"
                ),
                "emergency_contact_phone": (
                    "(85) 98888-8888"
                ),
            },
        )

        for index, registration in enumerate(
            registrations
        ):
            prefix = f"participants-{index}"

            data[f"{prefix}-id"] = str(
                registration.id
            )

            for field_name, value in (
                participants[index].items()
            ):
                data[f"{prefix}-{field_name}"] = value

        return data

    def test_login_is_required(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse("accounts:login"),
            response.url,
        )

    def test_page_creates_one_form_per_ticket(self):
        self.client.force_login(self.buyer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "registrations/participant_form.html",
        )

        self.assertEqual(
            self.registration_queryset().count(),
            2,
        )

        formset = response.context["formset"]

        self.assertEqual(
            formset.total_form_count(),
            2,
        )
        self.assertEqual(
            [
                form.instance.position
                for form in formset.forms 
            ],
            [1,2],
       
        )

    def test_other_buyer_receives_404(self):
        self.client.force_login(self.other_buyer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

        self.assertFalse(
            self.registration_queryset().exists()
        )

    def test_valid_post_saves_every_participant(self):
        self.client.force_login(self.buyer)

        response = self.client.post(
            self.url,
            self.valid_post_data(),
        )

        self.assertRedirects(
            response,
            self.url,
            fetch_redirect_response=False,
        )

        registrations = list(
            self.registration_queryset()
        )

        self.assertEqual(
            registrations[0].full_name,
            "Ana Participante",
        )
        self.assertEqual(
            registrations[0].document_number,
            "52998224725",
        )
        self.assertEqual(
            registrations[0].email,
            "ana@example.com",
        )
        self.assertEqual(
            registrations[0].phone,
            "85999999999",
        )

        self.assertEqual(
            registrations[1].document_number,
            "BR 123456",
        )
        self.assertEqual(
            registrations[1].emergency_contact_phone,
            "85988888888",
        )

        self.assertTrue(
            all(
                registration.completed_at is not None
                for registration in registrations
            )
        )

    def test_invalid_participant_saves_nothing(self):
        self.client.force_login(self.buyer)

        data = self.valid_post_data()
        data[
            "participants-1-document_type"
        ] = "cpf"
        data[
            "participants-1-document_number"
        ] = "111.111.111-11"

        response = self.client.post(
            self.url,
            data,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Informe um CPF válido.",
        )

        for registration in self.registration_queryset():
            self.assertEqual(
                registration.full_name,
                "",
            )
            self.assertIsNone(
                registration.completed_at
            )

    def test_missing_participant_is_rejected(self):
        self.client.force_login(self.buyer)

        data = self.valid_post_data()
        data["participants-TOTAL_FORMS"] = "1"
        data["participants-INITIAL_FORMS"] = "1"

        for key in list(data):
            if key.startswith("participants-1-"):
                del data[key]

        response = self.client.post(
            self.url,
            data,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "A lista de participantes foi alterada.",
        )

        self.assertFalse(
            self.registration_queryset().filter(
                completed_at__isnull=False,
            ).exists()
        )

    def test_expired_order_is_redirected_and_persisted(self):
        self.client.force_login(self.buyer)

        self.order.reservation_expires_at = (
            timezone.now() - timedelta(seconds=1)
        )
        self.order.save(
            update_fields=(
                "reservation_expires_at",
                "updated_at",
            )
        )

        response = self.client.get(self.url)

        self.assertRedirects(
            response,
            reverse(
                "orders:checkout-detail",
                kwargs={
                    "public_code": self.order.public_code,
                },
            ),
            fetch_redirect_response=False,
        )

        self.order.refresh_from_db()

        self.assertEqual(
            self.order.status,
            OrderStatus.EXPIRED,
        )