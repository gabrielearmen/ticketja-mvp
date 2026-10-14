from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import ANY, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
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
from apps.registrations.models import Registration
from apps.registrations.services import (
    ensure_registration_slots,
)

from .models import (
    Payment,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
)


class PaymentCheckoutViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.buyer = user_model.objects.create_user(
            email="pagamento-view@example.com",
            password="Senha-Segura!2026",
        )

        cls.other_buyer = user_model.objects.create_user(
            email="outro-pagamento-view@example.com",
            password="Senha-Segura!2026",
        )

        cls.organization = Organization.objects.create(
            name="Organização Pagamento View",
            slug="organizacao-pagamento-view",
            status=OrganizationStatus.APPROVED,
        )

        now = timezone.now()

        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Corrida PIX",
            summary="Evento de teste do pagamento.",
            sport_category=SportCategory.RUNNING,
            event_datetime=now + timedelta(days=30),
            city="Fortaleza",
            state="CE",
            address="Avenida Teste, 100",
            capacity=100,
            status=EventStatus.PUBLISHED,
        )

        cls.ticket_type = TicketType.objects.create(
            event=cls.event,
            name="Ingresso Geral",
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

    def setUp(self):
        now = timezone.now()

        self.order = Order.objects.create(
            buyer=self.buyer,
            organization=self.organization,
            event=self.event,
            status=OrderStatus.AWAITING_PAYMENT,
            subtotal=Decimal("50.00"),
            service_fee=Decimal("0.00"),
            total=Decimal("50.00"),
            reservation_expires_at=(
                now + timedelta(minutes=15)
            ),
        )

        self.order_item = OrderItem.objects.create(
            order=self.order,
            ticket_type=self.ticket_type,
            ticket_lot=self.ticket_lot,
            quantity=1,
            unit_price=Decimal("50.00"),
            subtotal=Decimal("50.00"),
        )

        self.participant_url = reverse(
            "registrations:participants",
            kwargs={
                "public_code": self.order.public_code,
            },
        )

        self.payment_url = reverse(
            "payments:detail",
            kwargs={
                "public_code": self.order.public_code,
            },
        )

    def participant_post_data(self):
        ensure_registration_slots(
            order_id=self.order.id,
            buyer=self.buyer,
        )

        registration = Registration.objects.get(
            order_item=self.order_item
        )

        return {
            "participants-TOTAL_FORMS": "1",
            "participants-INITIAL_FORMS": "1",
            "participants-MIN_NUM_FORMS": "0",
            "participants-MAX_NUM_FORMS": "1000",
            "participants-0-id": str(registration.id),
            "participants-0-full_name": (
                "Participante PIX"
            ),
            "participants-0-document_type": "cpf",
            "participants-0-document_number": (
                "529.982.247-25"
            ),
            "participants-0-birth_date": "1990-01-10",
            "participants-0-email": (
                "participante@example.com"
            ),
            "participants-0-phone": "",
            "participants-0-emergency_contact_name": "",
            "participants-0-emergency_contact_phone": "",
            "submit_action": "continue",
        }

    def create_pending_payment(self):
        return Payment.objects.create(
            order=self.order,
            attempt_number=1,
            provider=PaymentProvider.MERCADO_PAGO,
            method=PaymentMethod.PIX,
            status=PaymentStatus.PENDING,
            amount=self.order.total,
            platform_fee=Decimal("0.00"),
            provider_order_id="ORD-VIEW-001",
            provider_payment_id="PAY-VIEW-001",
            provider_status="action_required",
            provider_status_detail="waiting_transfer",
            pix_copy_paste="PIX-CODE-VIEW-001",
            pix_qr_code_base64="BASE64-VIEW-001",
            checkout_url=(
                "https://www.mercadopago.com.br/"
                "sandbox/payments/view"
            ),
            expires_at=self.order.reservation_expires_at,
        )

    @patch(
        "apps.registrations.views."
        "initiate_order_payment"
    )
    def test_continue_saves_and_redirects_to_payment(
        self,
        payment_service,
    ):
        payment_service.return_value = SimpleNamespace(
            is_free=False,
        )

        self.client.force_login(self.buyer)

        response = self.client.post(
            self.participant_url,
            self.participant_post_data(),
        )

        self.assertRedirects(
            response,
            self.payment_url,
            fetch_redirect_response=False,
        )

        registration = Registration.objects.get(
            order_item=self.order_item
        )

        self.assertEqual(
            registration.full_name,
            "Participante PIX",
        )
        self.assertIsNotNone(
            registration.completed_at
        )

        payment_service.assert_called_once_with(
            order_id=self.order.id,
            buyer=self.buyer,
        )

    @override_settings(
        MARKETPLACE_PAYMENTS_ENABLED=True,
        MARKETPLACE_CHECKOUT_MODE="pix",
    )
    @patch(
        "apps.registrations.views."
        "initiate_order_payment"
    )
    def test_marketplace_continue_redirects_to_payer_details(
        self,
        payment_service,
    ):
        self.client.force_login(self.buyer)

        response = self.client.post(
            self.participant_url,
            self.participant_post_data(),
        )

        self.assertRedirects(
            response,
            reverse(
                "payments:payer-details",
                kwargs={"public_code": self.order.public_code},
            ),
            fetch_redirect_response=False,
        )
        payment_service.assert_not_called()

    @override_settings(
        MARKETPLACE_PAYMENTS_ENABLED=True,
        MARKETPLACE_CHECKOUT_MODE="pix",
    )
    @patch("apps.payments.views.initiate_order_payment")
    def test_payer_form_starts_payment_with_validated_cpf(
        self,
        payment_service,
    ):
        payment_service.return_value = SimpleNamespace(
            is_free=False,
        )
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse(
                "payments:payer-details",
                kwargs={"public_code": self.order.public_code},
            ),
            {
                "full_name": "Maria da Silva",
                "document_number": "529.982.247-25",
            },
        )

        self.assertRedirects(
            response,
            self.payment_url,
            fetch_redirect_response=False,
        )
        payment_service.assert_called_once_with(
            order_id=self.order.id,
            buyer=self.buyer,
            payer_data={
                "first_name": "Maria",
                "last_name": "da Silva",
                "document_type": "CPF",
                "document_number": "52998224725",
            },
            return_urls=None,
        )

    @override_settings(
        MARKETPLACE_PAYMENTS_ENABLED=True,
        MARKETPLACE_CHECKOUT_MODE="pix",
    )
    @patch("apps.payments.views.initiate_order_payment")
    def test_invalid_payer_cpf_does_not_start_payment(
        self,
        payment_service,
    ):
        self.client.force_login(self.buyer)

        response = self.client.post(
            reverse(
                "payments:payer-details",
                kwargs={"public_code": self.order.public_code},
            ),
            {
                "full_name": "Maria da Silva",
                "document_number": "111.111.111-11",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Informe um CPF válido")
        payment_service.assert_not_called()

    @override_settings(
        MARKETPLACE_PAYMENTS_ENABLED=True,
        MARKETPLACE_CHECKOUT_MODE="checkout_pro",
    )
    @patch("apps.payments.views.initiate_order_payment")
    def test_checkout_pro_redirects_to_provider_without_collecting_card_data(
        self,
        payment_service,
    ):
        checkout_url = (
            "https://www.mercadopago.com.br/"
            "checkout/v1/redirect?order_id=ORD-001"
        )
        payment_service.return_value = SimpleNamespace(
            is_free=False,
            payment=SimpleNamespace(
                checkout_url=checkout_url,
            ),
        )
        self.client.force_login(self.buyer)
        url = reverse(
            "payments:payer-details",
            kwargs={"public_code": self.order.public_code},
        )

        page = self.client.get(url)

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Ir para o Mercado Pago")
        self.assertNotContains(page, "CPF do pagador")

        response = self.client.post(url, {})

        self.assertRedirects(
            response,
            checkout_url,
            fetch_redirect_response=False,
        )
        payment_service.assert_called_once_with(
            order_id=self.order.id,
            buyer=self.buyer,
            payer_data=None,
            return_urls=ANY,
        )

    def test_checkout_return_does_not_trust_provider_query_status(self):
        self.create_pending_payment()
        self.client.force_login(self.buyer)

        response = self.client.get(
            reverse(
                "payments:return",
                kwargs={
                    "public_code": self.order.public_code,
                    "outcome": "sucesso",
                },
            ),
            {"status": "approved"},
        )

        self.assertRedirects(
            response,
            self.payment_url,
            fetch_redirect_response=False,
        )
        self.order.refresh_from_db()
        self.assertEqual(
            self.order.status,
            OrderStatus.AWAITING_PAYMENT,
        )

    def test_payment_page_displays_pix(self):
        self.create_pending_payment()
        self.client.force_login(self.buyer)

        response = self.client.get(self.payment_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "payments/payment_detail.html",
        )
        self.assertContains(
            response,
            "PIX-CODE-VIEW-001",
        )
        self.assertContains(
            response,
            "Copiar código PIX",
        )

    def test_refresh_does_not_create_another_payment(self):
        self.create_pending_payment()
        self.client.force_login(self.buyer)

        self.client.get(self.payment_url)
        self.client.get(self.payment_url)

        self.assertEqual(
            Payment.objects.filter(
                order=self.order
            ).count(),
            1,
        )

    def test_other_buyer_receives_404(self):
        self.create_pending_payment()
        self.client.force_login(self.other_buyer)

        response = self.client.get(self.payment_url)

        self.assertEqual(response.status_code, 404)

    def test_expired_payment_hides_pix_code(self):
        payment = self.create_pending_payment()
        expired_at = timezone.now() - timedelta(seconds=1)

        self.order.reservation_expires_at = expired_at
        self.order.save(
            update_fields=(
                "reservation_expires_at",
                "updated_at",
            )
        )

        payment.expires_at = expired_at
        payment.save(
            update_fields=(
                "expires_at",
                "updated_at",
            )
        )

        self.client.force_login(self.buyer)

        response = self.client.get(self.payment_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Reserva expirada",
        )
        self.assertNotContains(
            response,
            "PIX-CODE-VIEW-001",
        )

        self.order.refresh_from_db()

        self.assertEqual(
            self.order.status,
            OrderStatus.EXPIRED,
        )
