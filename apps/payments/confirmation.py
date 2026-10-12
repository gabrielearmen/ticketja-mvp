from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.events.models import TicketLot
from apps.kits.models import (
    KitOption,
    RegistrationKitSelection,
)
from apps.orders.models import (
    Order,
    OrderItem,
    OrderStatus,
)

from .models import Payment, PaymentStatus


PROVIDER_PENDING_STATUSES = {
    "created",
    "processing",
    "action_required",
    "pending",
    "in_process",
    "authorized",
}


class PaymentConfirmationError(Exception):
    """
    Impede uma transição financeira insegura ou inconsistente.
    """


@dataclass(frozen=True, slots=True)
class PaymentConfirmationResult:
    payment: Payment
    order: Order
    transition: str
    already_finalized: bool


def _money(value):
    try:
        return Decimal(str(value)).quantize(
            Decimal("0.01")
        )
    except (InvalidOperation, TypeError, ValueError) as error:
        raise PaymentConfirmationError(
            "O provedor retornou um valor monetário inválido."
        ) from error


def _normalize_provider_value(value):
    return str(value or "").strip().lower()


def _normalize_datetime(value):
    if value is None:
        return None

    if timezone.is_naive(value):
        return timezone.make_aware(value)

    return value


def _validate_snapshot(*, payment, snapshot):
    if (
        snapshot.provider_order_id
        != payment.provider_order_id
    ):
        raise PaymentConfirmationError(
            "A ordem consultada não corresponde "
            "à cobrança registrada."
        )

    if not snapshot.provider_payment_id:
        raise PaymentConfirmationError(
            "O provedor não retornou o identificador "
            "do pagamento."
        )

    if (
        payment.provider_payment_id
        and payment.provider_payment_id
        != snapshot.provider_payment_id
    ):
        raise PaymentConfirmationError(
            "O identificador do pagamento diverge "
            "da cobrança registrada."
        )

    if not snapshot.external_reference:
        raise PaymentConfirmationError(
            "O provedor não retornou a referência externa."
        )

    if (
        snapshot.external_reference
        != payment.external_reference
    ):
        raise PaymentConfirmationError(
            "A referência externa não pertence "
            "ao pagamento registrado."
        )

    if _money(snapshot.amount) != _money(payment.amount):
        raise PaymentConfirmationError(
            "O valor aprovado diverge do total "
            "congelado no pedido."
        )


def _inventory_filter(*, at):
    return (
        Q(order__status=OrderStatus.PAID)
        | Q(
            order__status=OrderStatus.AWAITING_PAYMENT,
            order__reservation_expires_at__gt=at,
        )
    )


def _lock_and_validate_ticket_inventory(*, order, at):
    """
    Bloqueia os lotes e garante que uma reserva expirada não seja
    reativada quando suas vagas já tiverem sido ocupadas.
    """
    order_items = list(
        OrderItem.objects
        .select_for_update()
        .filter(order=order)
        .order_by("ticket_lot_id", "id")
    )

    if not order_items:
        raise PaymentConfirmationError(
            "O pedido não possui ingressos."
        )

    requested_by_lot = Counter()

    for item in order_items:
        requested_by_lot[item.ticket_lot_id] += (
            item.quantity
        )

    locked_lots = list(
        TicketLot.objects
        .select_for_update()
        .filter(id__in=requested_by_lot)
        .order_by("id")
    )

    lots_by_id = {
        lot.id: lot
        for lot in locked_lots
    }

    if len(lots_by_id) != len(requested_by_lot):
        raise PaymentConfirmationError(
            "Um dos lotes do pedido não está disponível."
        )

    committed_rows = (
        OrderItem.objects
        .exclude(order=order)
        .filter(ticket_lot_id__in=requested_by_lot)
        .filter(_inventory_filter(at=at))
        .values("ticket_lot_id")
        .annotate(
            total=Coalesce(
                Sum("quantity"),
                Value(0),
                output_field=IntegerField(),
            )
        )
    )

    committed_by_lot = {
        row["ticket_lot_id"]: row["total"]
        for row in committed_rows
    }

    for lot_id, requested_quantity in (
        requested_by_lot.items()
    ):
        lot = lots_by_id[lot_id]
        other_quantity = committed_by_lot.get(
            lot_id,
            0,
        )

        if other_quantity + requested_quantity > lot.quantity:
            raise PaymentConfirmationError(
                "A reserva expirou e as vagas do lote "
                "já foram ocupadas. O pagamento exige "
                "conciliação e eventual reembolso."
            )


def _lock_and_validate_kit_inventory(*, order, at):
    """
    Aplica ao estoque dos kits a mesma proteção usada nos lotes.
    """
    selections = list(
        RegistrationKitSelection.objects
        .select_for_update()
        .filter(
            registration__order_item__order=order,
        )
        .order_by("option_id", "id")
    )

    if not selections:
        return

    requested_by_option = Counter(
        selection.option_id
        for selection in selections
    )

    locked_options = list(
        KitOption.objects
        .select_for_update()
        .filter(id__in=requested_by_option)
        .order_by("id")
    )

    options_by_id = {
        option.id: option
        for option in locked_options
    }

    if len(options_by_id) != len(requested_by_option):
        raise PaymentConfirmationError(
            "Uma das opções de kit não está disponível."
        )

    holding_filter = (
        Q(
            registration__order_item__order__status=(
                OrderStatus.PAID
            )
        )
        | Q(
            registration__order_item__order__status=(
                OrderStatus.AWAITING_PAYMENT
            ),
            registration__order_item__order__reservation_expires_at__gt=at,
        )
    )

    committed_rows = (
        RegistrationKitSelection.objects
        .exclude(
            registration__order_item__order=order,
        )
        .filter(option_id__in=requested_by_option)
        .filter(holding_filter)
        .values("option_id")
        .annotate(total=Count("id"))
    )

    committed_by_option = {
        row["option_id"]: row["total"]
        for row in committed_rows
    }

    for option_id, requested_quantity in (
        requested_by_option.items()
    ):
        option = options_by_id[option_id]
        other_quantity = committed_by_option.get(
            option_id,
            0,
        )

        if (
            other_quantity + requested_quantity
            > option.stock_quantity
        ):
            raise PaymentConfirmationError(
                "A reserva expirou e a opção de kit "
                f"“{option.kit.name} — {option.name}” "
                "não possui mais estoque. O pagamento "
                "exige conciliação e eventual reembolso."
            )


def _provider_outcome(snapshot):
    status = _normalize_provider_value(
        snapshot.provider_status
    )
    detail = _normalize_provider_value(
        snapshot.provider_status_detail
    )

    if (
        status == "refunded"
        or (
            status == "processed"
            and detail == "refunded"
        )
    ):
        return "refunded"

    if status in {"charged_back", "chargeback"}:
        return "charged_back"

    if status in {"processed", "approved"}:
        return "approved"

    if status == "expired":
        return "expired"

    if status in {"canceled", "cancelled"}:
        return "canceled"

    if status in {"failed", "rejected"}:
        return "failed"

    if status in PROVIDER_PENDING_STATUSES:
        return "pending"

    raise PaymentConfirmationError(
        "O provedor retornou uma situação "
        f"não reconhecida: {status or 'vazia'}."
    )


def _validate_approval_deadline(
    *,
    order,
    approved_at,
):
    if order.reservation_expires_at is None:
        raise PaymentConfirmationError(
            "O pedido não possui prazo de reserva."
        )

    if approved_at > order.reservation_expires_at:
        raise PaymentConfirmationError(
            "O pagamento foi aprovado depois do término "
            "da reserva. A confirmação automática foi "
            "bloqueada para evitar excesso de vendas."
        )


@transaction.atomic
def reconcile_payment_snapshot(
    *,
    payment_id,
    snapshot,
    at=None,
):
    """
    Concilia a situação consultada diretamente no provedor.

    Ordem dos bloqueios:
    1. pedido;
    2. pagamento;
    3. itens e lotes;
    4. escolhas e opções de kits.

    Essa ordem reduz o risco de deadlocks e impede duas
    confirmações simultâneas do mesmo pedido.
    """
    reference_time = at or timezone.now()

    payment_reference = (
        Payment.objects
        .only("id", "order_id")
        .get(id=payment_id)
    )

    order = (
        Order.objects
        .select_for_update()
        .get(id=payment_reference.order_id)
    )

    payment = (
        Payment.objects
        .select_for_update()
        .get(id=payment_id)
    )

    _validate_snapshot(
        payment=payment,
        snapshot=snapshot,
    )

    provider_status = _normalize_provider_value(
        snapshot.provider_status
    )
    provider_detail = _normalize_provider_value(
        snapshot.provider_status_detail
    )

    payment.provider_payment_id = (
        snapshot.provider_payment_id
    )
    payment.provider_status = provider_status
    payment.provider_status_detail = provider_detail
    payment.provider_fee = snapshot.provider_fee
    payment.net_amount = snapshot.net_amount
    payment.failure_code = ""
    payment.failure_message = ""

    payment_fields = {
        "provider_payment_id",
        "provider_status",
        "provider_status_detail",
        "provider_fee",
        "net_amount",
        "failure_code",
        "failure_message",
        "updated_at",
    }

    order_fields = set()
    outcome = _provider_outcome(snapshot)
    transition = "unchanged"
    already_finalized = False

    if outcome == "approved":
        approved_at = (
            _normalize_datetime(snapshot.approved_at)
            or reference_time
        )

        if (
            payment.status == PaymentStatus.APPROVED
            and order.status == OrderStatus.PAID
        ):
            already_finalized = True
            transition = "already_paid"

        else:
            if payment.status in {
                PaymentStatus.CANCELED,
                PaymentStatus.REFUNDED,
            }:
                raise PaymentConfirmationError(
                    "Uma cobrança cancelada ou reembolsada "
                    "não pode ser aprovada."
                )

            if order.status not in {
                OrderStatus.AWAITING_PAYMENT,
                OrderStatus.EXPIRED,
                OrderStatus.PAID,
            }:
                raise PaymentConfirmationError(
                    "O pedido não permite confirmação "
                    "de pagamento."
                )

            _validate_approval_deadline(
                order=order,
                approved_at=approved_at,
            )

            _lock_and_validate_ticket_inventory(
                order=order,
                at=reference_time,
            )

            _lock_and_validate_kit_inventory(
                order=order,
                at=reference_time,
            )

            other_approved_payment_exists = (
                Payment.objects
                .select_for_update()
                .filter(
                    order=order,
                    status=PaymentStatus.APPROVED,
                )
                .exclude(id=payment.id)
                .exists()
            )

            if other_approved_payment_exists:
                raise PaymentConfirmationError(
                    "O pedido já possui outro "
                    "pagamento aprovado."
                )

            payment.status = PaymentStatus.APPROVED
            payment.approved_at = approved_at
            payment_fields.update(
                {
                    "status",
                    "approved_at",
                }
            )

            order.status = OrderStatus.PAID
            order_fields.add("status")

            transition = "paid"

    elif outcome == "refunded":
        if (
            payment.status == PaymentStatus.REFUNDED
            and order.status == OrderStatus.REFUNDED
        ):
            already_finalized = True
            transition = "already_refunded"

        else:
            payment.status = PaymentStatus.REFUNDED
            payment.refunded_at = reference_time
            payment_fields.update(
                {
                    "status",
                    "refunded_at",
                }
            )

            order.status = OrderStatus.REFUNDED
            order_fields.add("status")

            transition = "refunded"

    elif outcome == "charged_back":
        if (
            payment.status == PaymentStatus.CHARGED_BACK
            and order.status == OrderStatus.CHARGED_BACK
        ):
            already_finalized = True
            transition = "already_charged_back"
        else:
            payment.status = PaymentStatus.CHARGED_BACK
            payment.charged_back_at = reference_time
            payment_fields.update(
                {
                    "status",
                    "charged_back_at",
                }
            )

            order.status = OrderStatus.CHARGED_BACK
            order_fields.add("status")
            transition = "charged_back"

    elif outcome == "expired":
        if (
            payment.status == PaymentStatus.APPROVED
            or order.status == OrderStatus.PAID
        ):
            raise PaymentConfirmationError(
                "Uma notificação de expiração não pode "
                "reverter um pedido pago."
            )

        if payment.status != PaymentStatus.EXPIRED:
            payment.status = PaymentStatus.EXPIRED
            payment_fields.add("status")

        if order.status == OrderStatus.AWAITING_PAYMENT:
            order.status = OrderStatus.EXPIRED
            order_fields.add("status")
            transition = "expired"
        else:
            transition = "already_expired"
            already_finalized = True

    elif outcome == "canceled":
        if (
            payment.status == PaymentStatus.APPROVED
            or order.status == OrderStatus.PAID
        ):
            raise PaymentConfirmationError(
                "Uma notificação de cancelamento não pode "
                "reverter um pedido pago."
            )

        if payment.status != PaymentStatus.CANCELED:
            payment.status = PaymentStatus.CANCELED
            payment.canceled_at = reference_time
            payment_fields.update(
                {
                    "status",
                    "canceled_at",
                }
            )

        if order.status == OrderStatus.AWAITING_PAYMENT:
            order.status = OrderStatus.CANCELED
            order_fields.add("status")
            transition = "canceled"
        else:
            transition = "already_closed"
            already_finalized = True

    elif outcome == "failed":
        if (
            payment.status == PaymentStatus.APPROVED
            or order.status == OrderStatus.PAID
        ):
            raise PaymentConfirmationError(
                "Uma falha do provedor não pode "
                "reverter um pedido pago."
            )

        payment.status = PaymentStatus.REJECTED
        payment.failure_code = "provider_failed"
        payment.failure_message = (
            "Pagamento recusado pelo provedor."
        )

        payment_fields.update(
            {
                "status",
                "failure_code",
                "failure_message",
            }
        )

        if (
            order.status == OrderStatus.AWAITING_PAYMENT
            and order.reservation_expires_at is not None
            and order.reservation_expires_at
            <= reference_time
        ):
            order.status = OrderStatus.EXPIRED
            order_fields.add("status")
            transition = "rejected_and_expired"
        else:
            transition = "rejected"

    elif outcome == "pending":
        if payment.status == PaymentStatus.CREATED:
            payment.status = PaymentStatus.PENDING
            payment_fields.add("status")
            transition = "pending"
        else:
            transition = "still_pending"

    payment.save(
        update_fields=tuple(payment_fields)
    )

    if order_fields:
        order_fields.add("updated_at")

        order.save(
            update_fields=tuple(order_fields)
        )

    return PaymentConfirmationResult(
        payment=payment,
        order=order,
        transition=transition,
        already_finalized=already_finalized,
    )
