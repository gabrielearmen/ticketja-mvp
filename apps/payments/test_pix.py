from datetime import timedelta, timezone as datetime_timezone
from decimal import Decimal
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import (
    SimpleTestCase,
    TestCase,
    override_settings,
)
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
from apps.marketplace.crypto import encrypt_secret
from apps.marketplace.models import (
    OrganizationPaymentAccount,
    PaymentAccountStatus,
)
from apps.organizations.models import (
    Organization,
    OrganizationStatus,
)
from apps.registrations.models import (
    DocumentType,
    Registration,
)

from .gateways.base import (
    HostedCheckoutItem,
    HostedCheckoutRequest,
    HostedCheckoutResult,
    PaymentGateway,
    PaymentGatewayTemporaryError,
    PaymentSnapshot,
    PixChargeRequest,
    PixChargeResult,
)
from .gateways.mercado_pago import (
    MercadoPagoGateway,
    _sanitized_provider_message,
)
from .models import (
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from .services import (
    CheckoutReturnUrls,
    initiate_order_payment,
)


PAYER_TEST_KEY = Fernet.generate_key().decode("ascii")


class FakePixGateway(PaymentGateway):
    def __init__(self, *, fail_once=False):
        self.create_calls = []
        self.fail_once = fail_once

    def create_pix_charge(self, request):
        self.create_calls.append(request)

        if self.fail_once:
            self.fail_once = False
            raise PaymentGatewayTemporaryError(
                "Falha temporária simulada."
            )

        return PixChargeResult(
            provider_order_id="ORD-TEST-001",
            provider_payment_id="PAY-TEST-001",
            provider_status="action_required",
            provider_status_detail="waiting_transfer",
            pix_copy_paste="000201TESTEPIX",
            pix_qr_code_base64="BASE64-TESTE",
            checkout_url=(
                "https://www.mercadopago.com.br/"
                "sandbox/payments/test"
            ),
            expires_at=request.expires_at,
        )

    def fetch_payment(self, provider_order_id):
        return PaymentSnapshot(
            provider_order_id=provider_order_id,
            provider_payment_id="PAY-TEST-001",
            provider_status="action_required",
            provider_status_detail="waiting_transfer",
            amount=Decimal("100.00"),
        )

    def cancel_payment(self, provider_order_id):
        return PaymentSnapshot(
            provider_order_id=provider_order_id,
            provider_payment_id="PAY-TEST-001",
            provider_status="canceled",
            provider_status_detail="canceled",
            amount=Decimal("100.00"),
        )


class FakeHostedCheckoutGateway(FakePixGateway):
    def __init__(self):
        super().__init__()
        self.checkout_calls = []

    def create_hosted_checkout(self, request):
        self.checkout_calls.append(request)

        return HostedCheckoutResult(
            provider_order_id="ORD-CHECKOUT-001",
            provider_status="created",
            provider_status_detail="created",
            checkout_url=(
                "https://www.mercadopago.com.br/"
                "checkout/v1/redirect?order_id=ORD-CHECKOUT-001"
            ),
            expires_at=request.expires_at,
        )


class MercadoPagoGatewayTests(SimpleTestCase):
    def test_creates_checkout_pro_order_with_marketplace_fee(self):
        gateway = MercadoPagoGateway(
            access_token="APP_USR-SELLER-TOKEN",
            api_base_url="https://api.mercadopago.com",
            timeout_seconds=15,
            use_orders_api=True,
        )
        provider_response = {
            "id": "ORD-123",
            "status": "created",
            "status_detail": "created",
            "checkout_url": (
                "https://www.mercadopago.com.br/"
                "checkout/v1/redirect?order_id=ORD-123"
            ),
        }
        request_data = HostedCheckoutRequest(
            payment_id=__import__("uuid").uuid4(),
            idempotency_key=__import__("uuid").uuid4(),
            external_reference="TJP-CHECKOUT123",
            description="Pedido de teste",
            amount=Decimal("108.00"),
            platform_fee=Decimal("8.00"),
            payer_email="comprador@example.com",
            expires_at=timezone.now() + timedelta(minutes=35),
            expiration_seconds=35 * 60,
            success_url="https://ticketja.example/sucesso/",
            pending_url="https://ticketja.example/pendente/",
            failure_url="https://ticketja.example/falha/",
            items=(
                HostedCheckoutItem(
                    title="Ingresso Geral",
                    quantity=1,
                    unit_price=Decimal("100.00"),
                ),
                HostedCheckoutItem(
                    title="Taxa de serviço TicketJá",
                    quantity=1,
                    unit_price=Decimal("8.00"),
                ),
            ),
        )

        with patch.object(
            gateway,
            "_request_json",
            return_value=provider_response,
        ) as request_mock:
            result = gateway.create_hosted_checkout(request_data)

        request_kwargs = request_mock.call_args.kwargs
        payload = request_kwargs["payload"]

        self.assertEqual(request_kwargs["path"], "/v1/orders")
        self.assertEqual(payload["total_amount"], "108.00")
        self.assertEqual(payload["marketplace_fee"], "8.00")
        self.assertEqual(payload["expiration_time"], "PT35M")
        self.assertEqual(payload["processing_mode"], "manual")
        self.assertEqual(payload["capture_mode"], "automatic_async")
        self.assertEqual(
            payload["config"]["online"]["auto_return"],
            "all",
        )
        self.assertEqual(result.provider_order_id, "ORD-123")
        self.assertNotIn("unit_measure", payload["items"][0])
        self.assertNotIn("total_amount", payload["items"][0])

    def test_sanitizes_orders_api_error_list(self):
        message = _sanitized_provider_message(
            {
                "errors": [
                    {
                        "code": "unsupported_properties",
                        "message": "Property unit_measure is not supported",
                    }
                ]
            },
            400,
        )

        self.assertIn("unsupported_properties", message)
        self.assertIn("unit_measure", message)

    @override_settings(MERCADO_PAGO_TEST_MODE=True)
    def test_creates_pix_with_idempotency_and_qr_code(self):
        gateway = MercadoPagoGateway(
            access_token="APP_USR-TEST-TOKEN",
            api_base_url=(
                "https://api.mercadopago.com"
            ),
            timeout_seconds=15,
        )

        provider_response = {
            "id": "PAY-123",
            "status": "pending",
            "status_detail": "pending_waiting_transfer",
            "transaction_amount": 100.0,
            "point_of_interaction": {
                "transaction_data": {
                    "ticket_url": (
                        "https://www.mercadopago.com.br/"
                        "sandbox/payments/123"
                    ),
                    "qr_code": "PIX-COPIA-E-COLA",
                    "qr_code_base64": "",
                }
            },
        }

        request_data = PixChargeRequest(
            payment_id=(
                __import__("uuid").uuid4()
            ),
            idempotency_key=(
                __import__("uuid").uuid4()
            ),
            external_reference="TJP-TESTE123",
            description="Pedido de teste",
            amount=Decimal("100.00"),
            platform_fee=Decimal("7.50"),
            payer_email="comprador@example.com",
            payer_first_name="Maria",
            payer_last_name="Silva",
            payer_document_type="CPF",
            payer_document_number="52998224725",
            expires_at=(
                timezone.now()
                + timedelta(minutes=30)
            ),
        )

        with patch.object(
            gateway,
            "_request_json",
            return_value=provider_response,
        ) as request_mock:
            result = gateway.create_pix_charge(
                request_data
            )

        request_kwargs = (
            request_mock.call_args.kwargs
        )

        self.assertEqual(
            request_kwargs["method"],
            "POST",
        )
        self.assertEqual(
            request_kwargs["path"],
            "/v1/payments",
        )
        self.assertEqual(
            request_kwargs["idempotency_key"],
            request_data.idempotency_key,
        )
        self.assertEqual(
            request_kwargs["payload"]["transaction_amount"],
            100.0,
        )
        self.assertEqual(
            request_kwargs["payload"]["application_fee"],
            7.5,
        )
        self.assertEqual(
            request_kwargs["payload"]["payer"]["first_name"],
            "APRO",
        )
        self.assertEqual(
            request_kwargs["payload"]["payer"]["identification"],
            {"type": "CPF", "number": "52998224725"},
        )
        self.assertEqual(
            request_kwargs["payload"]["date_of_expiration"],
            request_data.expires_at.astimezone(
                datetime_timezone.utc
            ).isoformat(timespec="milliseconds"),
        )
        self.assertEqual(
            result.provider_order_id,
            "PAY-123",
        )
        self.assertEqual(
            result.pix_copy_paste,
            "PIX-COPIA-E-COLA",
        )
        self.assertEqual(
            result.pix_qr_code_base64,
            "",
        )

    def test_snapshot_separates_provider_fee_from_platform_fee(self):
        gateway = MercadoPagoGateway(
            access_token="APP_USR-TEST-TOKEN",
            api_base_url="https://api.mercadopago.com",
            timeout_seconds=15,
        )

        snapshot = gateway._snapshot_from_payment(
            {
                "id": "PAY-123",
                "status": "approved",
                "status_detail": "accredited",
                "transaction_amount": 108,
                "external_reference": "TJP-TESTE123",
                "fee_details": [
                    {"type": "mercadopago_fee", "amount": 4.50},
                    {"type": "application_fee", "amount": 8.00},
                ],
                "transaction_details": {
                    "net_received_amount": 95.50,
                },
            }
        )

        self.assertEqual(snapshot.provider_fee, Decimal("4.50"))
        self.assertEqual(snapshot.net_amount, Decimal("95.50"))


class PixPaymentServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        cls.buyer = user_model.objects.create_user(
            email="buyer-pix@example.com",
            password="Senha-Segura!2026",
        )

        cls.other_buyer = user_model.objects.create_user(
            email="other-pix@example.com",
            password="Senha-Segura!2026",
        )

        cls.organization = Organization.objects.create(
            name="Organização PIX",
            slug="organizacao-pix",
            status=OrganizationStatus.APPROVED,
        )

        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Evento PIX",
            summary="Evento utilizado nos testes PIX.",
            sport_category=SportCategory.RUNNING,
            event_datetime=(
                timezone.now() + timedelta(days=30)
            ),
            city="Fortaleza",
            state="CE",
            address="Avenida dos Testes, 100",
            capacity=100,
            status=EventStatus.PUBLISHED,
        )

        cls.ticket_type = TicketType.objects.create(
            event=cls.event,
            name="Ingresso Geral",
            description="Ingresso dos testes.",
            capacity=100,
            is_active=True,
        )

        cls.ticket_lot = TicketLot.objects.create(
            ticket_type=cls.ticket_type,
            name="Primeiro lote",
            price=Decimal("100.00"),
            quantity=100,
            sales_start=(
                timezone.now() - timedelta(days=1)
            ),
            sales_end=(
                timezone.now() + timedelta(days=20)
            ),
            is_active=True,
        )

    def create_ready_order(self, *, total="100.00"):
        amount = Decimal(total)

        order = Order.objects.create(
            buyer=self.buyer,
            organization=self.organization,
            event=self.event,
            status=OrderStatus.AWAITING_PAYMENT,
            subtotal=amount,
            service_fee=Decimal("0.00"),
            total=amount,
            reservation_expires_at=(
                timezone.now() + timedelta(minutes=15)
            ),
        )

        item = OrderItem.objects.create(
            order=order,
            ticket_type=self.ticket_type,
            ticket_lot=self.ticket_lot,
            quantity=1,
            unit_price=amount,
            subtotal=amount,
        )

        Registration.objects.create(
            order_item=item,
            position=1,
            full_name="Participante Teste",
            document_type=DocumentType.CPF,
            document_number="52998224725",
            birth_date=timezone.localdate().replace(
                year=1990
            ),
            email="participante@example.com",
            completed_at=timezone.now(),
        )

        return order

    def test_creates_pix_and_extends_reservation(self):
        order = self.create_ready_order()
        gateway = FakePixGateway()

        before = timezone.now()

        result = initiate_order_payment(
            order_id=order.id,
            buyer=self.buyer,
            gateway=gateway,
        )

        order.refresh_from_db()
        result.payment.refresh_from_db()

        self.assertEqual(
            result.payment.status,
            PaymentStatus.PENDING,
        )
        self.assertEqual(
            result.payment.method,
            PaymentMethod.PIX,
        )
        self.assertEqual(
            result.payment.pix_copy_paste,
            "000201TESTEPIX",
        )
        self.assertEqual(
            order.reservation_expires_at,
            result.payment.expires_at,
        )
        self.assertGreaterEqual(
            order.reservation_expires_at,
            before + timedelta(minutes=29),
        )
        self.assertEqual(
            len(gateway.create_calls),
            1,
        )

    @override_settings(
        MARKETPLACE_PAYMENTS_ENABLED=True,
        MARKETPLACE_CHECKOUT_MODE="checkout_pro",
        MARKETPLACE_TOKEN_ENCRYPTION_KEYS=PAYER_TEST_KEY,
    )
    def test_marketplace_creates_hosted_checkout_without_card_data(self):
        order = self.create_ready_order()
        order.platform_fee = Decimal("8.00")
        order.fee_policy_reference = __import__("uuid").uuid4()
        order.save(
            update_fields=(
                "platform_fee",
                "fee_policy_reference",
                "updated_at",
            )
        )
        OrganizationPaymentAccount.objects.create(
            organization=self.organization,
            status=PaymentAccountStatus.ACTIVE,
            provider_user_id="seller-checkout-001",
            access_token_ciphertext=encrypt_secret(
                "seller-oauth-token"
            ),
            connected_at=timezone.now(),
        )
        gateway = FakeHostedCheckoutGateway()
        return_urls = CheckoutReturnUrls(
            success="https://ticketja.example/sucesso/",
            pending="https://ticketja.example/pendente/",
            failure="https://ticketja.example/falha/",
        )

        result = initiate_order_payment(
            order_id=order.id,
            buyer=self.buyer,
            return_urls=return_urls,
            gateway=gateway,
        )

        result.payment.refresh_from_db()
        self.assertEqual(
            result.payment.method,
            PaymentMethod.CHECKOUT_PRO,
        )
        self.assertEqual(
            result.payment.provider_order_id,
            "ORD-CHECKOUT-001",
        )
        self.assertEqual(
            result.payment.payer_document_ciphertext,
            "",
        )
        self.assertEqual(len(gateway.checkout_calls), 1)
        checkout_request = gateway.checkout_calls[0]
        self.assertEqual(
            checkout_request.platform_fee,
            Decimal("8.00"),
        )
        self.assertEqual(
            sum(
                item.unit_price * item.quantity
                for item in checkout_request.items
            ),
            order.total,
        )

    @override_settings(
        MARKETPLACE_TOKEN_ENCRYPTION_KEYS=PAYER_TEST_KEY,
    )
    def test_payer_snapshot_is_encrypted_and_sent_to_gateway(self):
        order = self.create_ready_order()
        gateway = FakePixGateway()

        result = initiate_order_payment(
            order_id=order.id,
            buyer=self.buyer,
            gateway=gateway,
            payer_data={
                "first_name": "Maria",
                "last_name": "Silva",
                "document_type": "CPF",
                "document_number": "529.982.247-25",
            },
        )

        result.payment.refresh_from_db()
        request = gateway.create_calls[0]

        self.assertNotIn(
            "52998224725",
            result.payment.payer_document_ciphertext,
        )
        self.assertEqual(
            result.payment.payer_document_last4,
            "4725",
        )
        self.assertEqual(request.payer_first_name, "Maria")
        self.assertEqual(request.payer_last_name, "Silva")
        self.assertEqual(
            request.payer_document_number,
            "52998224725",
        )

    @override_settings(
        MARKETPLACE_PAYMENTS_ENABLED=True,
        MARKETPLACE_CHECKOUT_MODE="pix",
        MARKETPLACE_TOKEN_ENCRYPTION_KEYS=PAYER_TEST_KEY,
    )
    def test_marketplace_payment_requires_payer_details(self):
        order = self.create_ready_order()

        with self.assertRaises(ValidationError):
            initiate_order_payment(
                order_id=order.id,
                buyer=self.buyer,
                gateway=FakePixGateway(),
            )

        self.assertFalse(
            Payment.objects.filter(order=order).exists()
        )

    def test_repeated_request_does_not_create_second_pix(self):
        order = self.create_ready_order()
        gateway = FakePixGateway()

        first = initiate_order_payment(
            order_id=order.id,
            buyer=self.buyer,
            gateway=gateway,
        )

        second = initiate_order_payment(
            order_id=order.id,
            buyer=self.buyer,
            gateway=gateway,
        )

        self.assertEqual(
            first.payment.id,
            second.payment.id,
        )
        self.assertEqual(
            Payment.objects.filter(
                order=order
            ).count(),
            1,
        )
        self.assertEqual(
            len(gateway.create_calls),
            1,
        )

    def test_temporary_failure_reuses_same_key(self):
        order = self.create_ready_order()
        gateway = FakePixGateway(fail_once=True)

        with self.assertRaises(
            PaymentGatewayTemporaryError
        ):
            initiate_order_payment(
                order_id=order.id,
                buyer=self.buyer,
                gateway=gateway,
            )

        payment = Payment.objects.get(order=order)
        original_key = payment.idempotency_key

        result = initiate_order_payment(
            order_id=order.id,
            buyer=self.buyer,
            gateway=gateway,
        )

        self.assertEqual(
            result.payment.idempotency_key,
            original_key,
        )
        self.assertEqual(
            len(gateway.create_calls),
            2,
        )
        self.assertEqual(
            gateway.create_calls[0].idempotency_key,
            gateway.create_calls[1].idempotency_key,
        )

    def test_free_order_is_confirmed_without_gateway(self):
        order = self.create_ready_order(total="0.00")
        gateway = FakePixGateway()

        result = initiate_order_payment(
            order_id=order.id,
            buyer=self.buyer,
            gateway=gateway,
        )

        order.refresh_from_db()

        self.assertTrue(result.is_free)
        self.assertEqual(
            result.payment.status,
            PaymentStatus.APPROVED,
        )
        self.assertEqual(
            result.payment.method,
            PaymentMethod.FREE,
        )
        self.assertEqual(
            order.status,
            OrderStatus.PAID,
        )
        self.assertEqual(
            len(gateway.create_calls),
            0,
        )

    def test_incomplete_participant_blocks_payment(self):
        order = self.create_ready_order()

        Registration.objects.filter(
            order_item__order=order
        ).update(completed_at=None)

        with self.assertRaises(ValidationError):
            initiate_order_payment(
                order_id=order.id,
                buyer=self.buyer,
                gateway=FakePixGateway(),
            )

        self.assertFalse(
            Payment.objects.filter(
                order=order
            ).exists()
        )

    def test_another_buyer_cannot_pay_order(self):
        order = self.create_ready_order()

        with self.assertRaises(ValidationError):
            initiate_order_payment(
                order_id=order.id,
                buyer=self.other_buyer,
                gateway=FakePixGateway(),
            )

        self.assertFalse(
            Payment.objects.filter(
                order=order
            ).exists()
        )
