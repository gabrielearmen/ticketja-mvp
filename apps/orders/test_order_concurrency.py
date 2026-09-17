import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import (
    close_old_connections,
    connection,
    connections,
)
from django.test import TransactionTestCase
from django.utils import timezone

from apps.events.models import (
    Event,
    EventStatus,
    SportCategory,
    TicketLot,
    TicketType,
)
from apps.organizations.models import (
    Organization,
    OrganizationStatus,
)

from .models import Order, OrderItem
from .services import create_reservation_order


class OrderConcurrencyTests(TransactionTestCase):
    def setUp(self):
        user_model = get_user_model()

        self.buyer_a = user_model.objects.create_user(
            email="concorrencia-a@example.com",
            password="Senha-Segura!2026",
        )

        self.buyer_b = user_model.objects.create_user(
            email="concorrencia-b@example.com",
            password="Senha-Segura!2026",
        )

        self.organization = Organization.objects.create(
            name="Organização Concorrência",
            slug="organizacao-concorrencia",
            status=OrganizationStatus.APPROVED,
        )

        self.event = Event.objects.create(
            organization=self.organization,
            title="Evento Concorrente",
            summary="Teste real de concorrência PostgreSQL.",
            sport_category=SportCategory.RUNNING,
            event_datetime=(
                timezone.now() + timedelta(days=30)
            ),
            city="Fortaleza",
            state="CE",
            address="Avenida Beira Mar, 1000",
            capacity=1,
            status=EventStatus.PUBLISHED,
        )

        self.ticket_type = TicketType.objects.create(
            event=self.event,
            name="Última Vaga",
            capacity=1,
            is_active=True,
        )

        self.ticket_lot = TicketLot.objects.create(
            ticket_type=self.ticket_type,
            name="Lote com Uma Vaga",
            price=Decimal("100.00"),
            quantity=1,
            sales_start=(
                timezone.now() - timedelta(days=1)
            ),
            sales_end=(
                timezone.now() + timedelta(days=10)
            ),
            is_active=True,
        )

    def concurrent_attempt(
        self,
        *,
        barrier,
        buyer_id,
        idempotency_key,
    ):
        close_old_connections()

        try:
            user_model = get_user_model()
            buyer = user_model.objects.get(id=buyer_id)

            barrier.wait(timeout=15)

            result = create_reservation_order(
                buyer=buyer,
                ticket_lot_id=self.ticket_lot.id,
                quantity=1,
                idempotency_key=idempotency_key,
            )

            return {
                "outcome": "success",
                "created": result.created,
                "order_id": result.order.id,
            }

        except ValidationError as error:
            return {
                "outcome": "rejected",
                "message": str(error),
            }

        finally:
            connections["default"].close()

    def test_two_buyers_cannot_reserve_the_last_vacancy(self):
        if connection.vendor != "postgresql":
            self.skipTest(
                "Este teste exige PostgreSQL."
            )

        barrier = Barrier(2)

        connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(
                    self.concurrent_attempt,
                    barrier=barrier,
                    buyer_id=self.buyer_a.id,
                    idempotency_key=uuid.uuid4(),
                ),
                executor.submit(
                    self.concurrent_attempt,
                    barrier=barrier,
                    buyer_id=self.buyer_b.id,
                    idempotency_key=uuid.uuid4(),
                ),
            )

            results = [
                future.result(timeout=30)
                for future in futures
            ]

        close_old_connections()

        successful_results = [
            result
            for result in results
            if result["outcome"] == "success"
        ]

        rejected_results = [
            result
            for result in results
            if result["outcome"] == "rejected"
        ]

        self.assertEqual(len(successful_results), 1)
        self.assertEqual(len(rejected_results), 1)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)
        self.assertEqual(
            OrderItem.objects.get().quantity,
            1,
        )

    def test_simultaneous_replay_creates_only_one_order(self):
        if connection.vendor != "postgresql":
            self.skipTest(
                "Este teste exige PostgreSQL."
            )

        barrier = Barrier(2)
        operation_key = uuid.uuid4()

        connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(
                    self.concurrent_attempt,
                    barrier=barrier,
                    buyer_id=self.buyer_a.id,
                    idempotency_key=operation_key,
                ),
                executor.submit(
                    self.concurrent_attempt,
                    barrier=barrier,
                    buyer_id=self.buyer_a.id,
                    idempotency_key=operation_key,
                ),
            )

            results = [
                future.result(timeout=30)
                for future in futures
            ]

        close_old_connections()

        self.assertTrue(
            all(
                result["outcome"] == "success"
                for result in results
            )
        )

        created_values = sorted(
            result["created"]
            for result in results
        )

        self.assertEqual(
            created_values,
            [False, True],
        )

        returned_order_ids = {
            result["order_id"]
            for result in results
        }

        self.assertEqual(len(returned_order_ids), 1)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)