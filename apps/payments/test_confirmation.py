from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
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
from apps.kits.selectors import (
    option_availabilities_for_kit,
)
from apps.orders.availability import (
    calculate_ticket_lot_availability,
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

from .confirmation import (
    PaymentConfirmationError,
    reconcile_payment_snapshot,
)
from .gateways.base import PaymentSnapshot
from .models import (
    Payment,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
)


class PaymentConfirmationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()

        cls.buyer = (
            get_user_model().objects.create_user(
                email="confirmacao@example.com",
                password="senha-forte-2026",
            )
        )

        cls.organization = Organization.objects.create(
            name="Organização Confirmação",
            slug="organizacao-confirmacao",
            status=OrganizationStatus.APPROVED,
        )

        cls.event = Event.objects.create(
            organization=cls.organization,
            title="Corrida Confirmação",
            summary="Evento para testes financeiros.",
            sport_category=SportCategory.RUNNING,
            event_datetime=now + timedelta(days=30),
            city="Fortaleza",
            state="CE",
            address="Avenida dos Testes, 100",
            capacity=10,
            status=EventStatus.PUBLISHED,
            cover_image="events/covers/teste.png",
        )

        cls.ticket_type = TicketType.objects.create(
            event=cls.event,
            name="Ingresso com kit",
            description="Ingresso de teste.",
            capacity=10,
            is_active=True,
        )

        cls.ticket_lot = TicketLot.objects.create(
            ticket_type=cls.ticket_type,
            name="Lote único",
            price=Decimal("60.00"),
            quantity=10,
            sales_start=now - timedelta(days=1),
            sales_end=now + timedelta(days=20),
            is_active=True,
        )

        cls.kit = EventKit.objects.create(
            event=cls.event,
            name="Camiseta",
            description="Camiseta do evento.",
            is_required=True,
            is_active=True,
        )

        TicketTypeKit.objects.create(
            kit=cls.kit,
            ticket_type=cls.ticket_type,
        )

        cls.option = KitOption.objects.create(
            kit=cls.kit,
            name="M",
            stock_quantity=10,
            is_active=True,
        )

        cls.order = Order.objects.create(
            buyer=cls.buyer,
            organization=cls.organization,
            event=cls.event,
            status=OrderStatus.AWAITING_PAYMENT,
            subtotal=Decimal("60.00"),
            service_fee=Decimal("0.00"),
            total=Decimal("60.00"),
            reservation_expires_at=(
                now + timedelta(minutes=30)
            ),
        )

        cls.order_item = OrderItem.objects.create(
            order=cls.order,
            ticket_type=cls.ticket_type,
            ticket_lot=cls.ticket_lot,
            quantity=1,
            unit_price=Decimal("60.00"),
            subtotal=Decimal("60.00"),
        )

        cls.registration = Registration.objects.create(
            order_item=cls.order_item,
            position=1,
        )

        RegistrationKitSelection.objects.create(
            registration=cls.registration,
            kit=cls.kit,
            option=cls.option,
        )

        cls.payment = Payment.objects.create(
            order=cls.order,
            attempt_number=1,
            provider=PaymentProvider.MERCADO_PAGO,
            method=PaymentMethod.PIX,
            status=PaymentStatus.PENDING,
            amount=Decimal("60.00"),
            platform_fee=Decimal("0.00"),
            provider_order_id="ORD-CONFIRM-001",
            provider_payment_id="PAY-CONFIRM-001",
            provider_status="action_required",
            provider_status_detail="waiting_transfer",
            expires_at=cls.order.reservation_expires_at,
        )

    def snapshot(
        self,
        *,
        status="processed",
        detail="accredited",
        approved_at=None,
    ):
        self.payment.refresh_from_db()

        return PaymentSnapshot(
            provider_order_id=(
                self.payment.provider_order_id
            ),
            provider_payment_id=(
                self.payment.provider_payment_id
            ),
            provider_status=status,
            provider_status_detail=detail,
            amount=self.payment.amount,
            approved_at=approved_at,
            external_reference=(
                self.payment.external_reference
            ),
        )

    def test_processed_payment_marks_order_as_paid(self):
        approved_at = timezone.now()

        result = reconcile_payment_snapshot(
            payment_id=self.payment.id,
            snapshot=self.snapshot(
                approved_at=approved_at,
            ),
            at=approved_at,
        )

        self.order.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(
            self.order.status,
            OrderStatus.PAID,
        )
        self.assertEqual(
            self.payment.status,
            PaymentStatus.APPROVED,
        )
        self.assertEqual(result.transition, "paid")

    def test_double_confirmation_is_idempotent(self):
        approved_at = timezone.now()
        snapshot = self.snapshot(
            approved_at=approved_at,
        )

        first = reconcile_payment_snapshot(
            payment_id=self.payment.id,
            snapshot=snapshot,
            at=approved_at,
        )

        second = reconcile_payment_snapshot(
            payment_id=self.payment.id,
            snapshot=snapshot,
            at=approved_at,
        )

        self.assertEqual(first.transition, "paid")
        self.assertTrue(second.already_finalized)
        self.assertEqual(
            second.transition,
            "already_paid",
        )

        self.assertEqual(
            Payment.objects.filter(
                order=self.order,
                status=PaymentStatus.APPROVED,
            ).count(),
            1,
        )

    def test_paid_order_keeps_ticket_and_kit_consumed(self):
        approved_at = timezone.now()

        reconcile_payment_snapshot(
            payment_id=self.payment.id,
            snapshot=self.snapshot(
                approved_at=approved_at,
            ),
            at=approved_at,
        )

        future = (
            self.order.reservation_expires_at
            + timedelta(hours=1)
        )

        ticket_availability = (
            calculate_ticket_lot_availability(
                ticket_lot=self.ticket_lot,
                at=future,
            )
        )

        kit_rows = option_availabilities_for_kit(
            kit=self.kit,
            at=future,
        )

        self.assertEqual(
            ticket_availability.committed_quantity,
            1,
        )
        self.assertEqual(
            kit_rows[0].reserved_quantity,
            1,
        )

    def test_expired_payment_releases_inventory(self):
        reference_time = timezone.now()

        reconcile_payment_snapshot(
            payment_id=self.payment.id,
            snapshot=self.snapshot(
                status="expired",
                detail="expired",
            ),
            at=reference_time,
        )

        self.order.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(
            self.order.status,
            OrderStatus.EXPIRED,
        )
        self.assertEqual(
            self.payment.status,
            PaymentStatus.EXPIRED,
        )

        availability = (
            calculate_ticket_lot_availability(
                ticket_lot=self.ticket_lot,
                at=reference_time,
            )
        )

        self.assertEqual(
            availability.committed_quantity,
            0,
        )

    def test_refund_releases_ticket_and_kit(self):
        reference_time = timezone.now()

        reconcile_payment_snapshot(
            payment_id=self.payment.id,
            snapshot=self.snapshot(
                approved_at=reference_time,
            ),
            at=reference_time,
        )

        reconcile_payment_snapshot(
            payment_id=self.payment.id,
            snapshot=self.snapshot(
                status="refunded",
                detail="refunded",
            ),
            at=reference_time + timedelta(minutes=1),
        )

        self.order.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(
            self.order.status,
            OrderStatus.REFUNDED,
        )
        self.assertEqual(
            self.payment.status,
            PaymentStatus.REFUNDED,
        )

        future = reference_time + timedelta(hours=1)

        ticket_availability = (
            calculate_ticket_lot_availability(
                ticket_lot=self.ticket_lot,
                at=future,
            )
        )

        kit_rows = option_availabilities_for_kit(
            kit=self.kit,
            at=future,
        )

        self.assertEqual(
            ticket_availability.committed_quantity,
            0,
        )
        self.assertEqual(
            kit_rows[0].reserved_quantity,
            0,
        )

    def test_chargeback_suspends_paid_order_idempotently(self):
        reference_time = timezone.now()

        reconcile_payment_snapshot(
            payment_id=self.payment.id,
            snapshot=self.snapshot(
                approved_at=reference_time,
            ),
            at=reference_time,
        )

        snapshot = self.snapshot(
            status="charged_back",
            detail="reimbursed",
        )
        first = reconcile_payment_snapshot(
            payment_id=self.payment.id,
            snapshot=snapshot,
            at=reference_time + timedelta(minutes=1),
        )
        second = reconcile_payment_snapshot(
            payment_id=self.payment.id,
            snapshot=snapshot,
            at=reference_time + timedelta(minutes=2),
        )

        self.order.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(
            self.order.status,
            OrderStatus.CHARGED_BACK,
        )
        self.assertEqual(
            self.payment.status,
            PaymentStatus.CHARGED_BACK,
        )
        self.assertEqual(first.transition, "charged_back")
        self.assertTrue(second.already_finalized)

    def test_late_approval_cannot_oversell(self):
        reference_time = timezone.now()
        expiration = reference_time - timedelta(minutes=5)

        self.order.status = OrderStatus.EXPIRED
        self.order.reservation_expires_at = expiration
        self.order.save(
            update_fields=(
                "status",
                "reservation_expires_at",
                "updated_at",
            )
        )

        self.ticket_lot.quantity = 1
        self.ticket_lot.save(
            update_fields=(
                "quantity",
                "updated_at",
            )
        )

        competing_order = Order.objects.create(
            buyer=self.buyer,
            organization=self.organization,
            event=self.event,
            status=OrderStatus.PAID,
            subtotal=Decimal("60.00"),
            service_fee=Decimal("0.00"),
            total=Decimal("60.00"),
            reservation_expires_at=expiration,
        )

        OrderItem.objects.create(
            order=competing_order,
            ticket_type=self.ticket_type,
            ticket_lot=self.ticket_lot,
            quantity=1,
            unit_price=Decimal("60.00"),
            subtotal=Decimal("60.00"),
        )

        with self.assertRaises(
            PaymentConfirmationError
        ):
            reconcile_payment_snapshot(
                payment_id=self.payment.id,
                snapshot=self.snapshot(
                    approved_at=(
                        expiration
                        - timedelta(minutes=1)
                    ),
                ),
                at=reference_time,
            )

        self.order.refresh_from_db()
        self.payment.refresh_from_db()

        self.assertEqual(
            self.order.status,
            OrderStatus.EXPIRED,
        )
        self.assertEqual(
            self.payment.status,
            PaymentStatus.PENDING,
        )
