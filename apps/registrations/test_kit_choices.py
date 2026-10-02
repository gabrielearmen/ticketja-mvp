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
from apps.kits.models import (
    EventKit,
    KitOption,
    RegistrationKitSelection,
    TicketTypeKit,
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
)


class ParticipantKitChoiceViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.buyer = user_model.objects.create_user(
            email="comprador-formulario-kit@example.com",
            password="senha-segura-2026",
        )

        cls.organization = Organization.objects.create(
            name="Organização Formulário Kit",
            slug="organizacao-formulario-kit",
            status=OrganizationStatus.APPROVED,
        )

        now = timezone.now()

        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Corrida Formulário Kit",
            summary="Evento para testar escolhas individuais.",
            sport_category=SportCategory.RUNNING,
            event_datetime=now + timedelta(days=30),
            city="Fortaleza",
            state="CE",
            address="Avenida dos Atletas, 100",
            capacity=100,
            status=EventStatus.PUBLISHED,
            cover_image="events/covers/formulario-kit.png",
        )

        cls.ticket_type = TicketType.objects.create(
            event=cls.event,
            name="Ingresso 5 km",
            description="Ingresso com camiseta.",
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

        cls.kit = EventKit.objects.create(
            event=cls.event,
            name="Camiseta oficial",
            description="Escolha o tamanho da camiseta.",
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

    @property
    def kit_field_name(self):
        return f"kit_{self.kit.id.hex}"

    def registrations(self):
        ensure_registration_slots(
            order_id=self.order.id,
            buyer=self.buyer,
        )

        return list(
            Registration.objects
            .filter(order_item=self.order_item)
            .order_by("position")
        )

    def valid_post_data(
        self,
        *,
        first_option=None,
        second_option=None,
    ):
        registrations = self.registrations()

        first_option = (
            first_option or self.option_m
        )
        second_option = (
            second_option or self.option_g
        )

        data = {
            "participants-TOTAL_FORMS": "2",
            "participants-INITIAL_FORMS": "2",
            "participants-MIN_NUM_FORMS": "0",
            "participants-MAX_NUM_FORMS": "1000",
        }

        participant_rows = (
            {
                "full_name": "Ana Participante",
                "document_type": "cpf",
                "document_number": "529.982.247-25",
                "birth_date": "1990-01-10",
                "email": "ana@example.com",
                "phone": "",
                "emergency_contact_name": "",
                "emergency_contact_phone": "",
                "kit_option": first_option,
            },
            {
                "full_name": "Bruno Participante",
                "document_type": "passaporte",
                "document_number": "BR 123456",
                "birth_date": "1988-02-20",
                "email": "",
                "phone": "",
                "emergency_contact_name": "",
                "emergency_contact_phone": "",
                "kit_option": second_option,
            },
        )

        for index, registration in enumerate(
            registrations
        ):
            prefix = f"participants-{index}"
            participant = participant_rows[index]

            data[f"{prefix}-id"] = str(
                registration.id
            )

            for field_name in (
                "full_name",
                "document_type",
                "document_number",
                "birth_date",
                "email",
                "phone",
                "emergency_contact_name",
                "emergency_contact_phone",
            ):
                data[f"{prefix}-{field_name}"] = (
                    participant[field_name]
                )

            option = participant["kit_option"]

            data[
                f"{prefix}-{self.kit_field_name}"
            ] = (
                str(option.id)
                if option is not None
                else ""
            )

        return data

    def test_page_has_one_kit_selector_per_participant(self):
        self.client.force_login(self.buyer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        formset = response.context["formset"]

        self.assertEqual(len(formset.forms), 2)

        for form in formset.forms:
            self.assertIn(
                self.kit_field_name,
                form.fields,
            )

            choice_values = {
                value
                for value, label
                in form.fields[
                    self.kit_field_name
                ].choices
            }

            self.assertIn(
                str(self.option_m.id),
                choice_values,
            )
            self.assertIn(
                str(self.option_g.id),
                choice_values,
            )

        self.assertContains(
            response,
            "Camiseta oficial",
        )
        self.assertContains(
            response,
            "Escolha individual",
        )

    def test_each_participant_saves_own_option(self):
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

        selections = list(
            RegistrationKitSelection.objects
            .select_related("registration")
            .order_by("registration__position")
        )

        self.assertEqual(len(selections), 2)
        self.assertEqual(
            selections[0].option,
            self.option_m,
        )
        self.assertEqual(
            selections[1].option,
            self.option_g,
        )

    def test_required_kit_error_is_shown_in_form(self):
        self.client.force_login(self.buyer)

        data = self.valid_post_data()
        data[
            f"participants-0-{self.kit_field_name}"
        ] = ""

        response = self.client.post(
            self.url,
            data,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Selecione uma opção para este kit.",
        )
        self.assertFalse(
            RegistrationKitSelection.objects.exists()
        )
        self.assertFalse(
            Registration.objects.filter(
                completed_at__isnull=False,
            ).exists()
        )

    def test_combined_demand_above_stock_is_shown(self):
        self.client.force_login(self.buyer)

        response = self.client.post(
            self.url,
            self.valid_post_data(
                first_option=self.option_m,
                second_option=self.option_m,
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "não possui estoque suficiente",
        )
        self.assertFalse(
            RegistrationKitSelection.objects.exists()
        )
        self.assertFalse(
            Registration.objects.filter(
                completed_at__isnull=False,
            ).exists()
        )