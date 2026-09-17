import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from .availability import (
    lock_ticket_lot_and_calculate_availability,
    validate_reservation_quantity,
)
from .models import (
    MONEY_ZERO,
    Order,
    OrderItem,
    OrderStatus,
)


@dataclass(frozen=True, slots=True)
class OrderCreationResult:
    """
    Resultado da tentativa idempotente de criação.

    created=True:
        um pedido novo foi criado.

    created=False:
        a mesma requisição já havia sido processada e o pedido
        existente foi devolvido.
    """

    order: Order
    created: bool


def _normalize_uuid(*, value, field_name):
    """
    Converte uma entrada em UUID ou apresenta um erro controlado.
    """
    if isinstance(value, uuid.UUID):
        return value

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValidationError(
            {
                field_name: (
                    "O identificador informado é inválido."
                )
            }
        ) from error


def _validated_active_buyer(buyer):
    """
    Confirma que o comprador é autenticado, existe e está ativo.

    O usuário é consultado novamente no banco para não depender
    somente dos dados recebidos da requisição.
    """
    if (
        not getattr(buyer, "is_authenticated", False)
        or buyer.pk is None
    ):
        raise ValidationError(
            {
                "buyer": (
                    "É necessário entrar em uma conta ativa "
                    "para iniciar uma inscrição."
                )
            }
        )

    user_model = get_user_model()

    active_buyer = (
        user_model.objects
        .filter(
            pk=buyer.pk,
            is_active=True,
        )
        .first()
    )

    if active_buyer is None:
        raise ValidationError(
            {
                "buyer": (
                    "É necessário entrar em uma conta ativa "
                    "para iniciar uma inscrição."
                )
            }
        )

    return active_buyer


def _lock_idempotency_key(idempotency_key):
    """
    Serializa requisições que utilizam a mesma chave.

    O bloqueio consultivo pertence à transação do PostgreSQL e é
    liberado automaticamente no commit ou rollback.

    A consulta é parametrizada; a chave nunca é concatenada ao SQL.
    """
    advisory_lock_id = (
        idempotency_key.int
        & ((1 << 63) - 1)
    )

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            [advisory_lock_id],
        )


def _order_for_idempotency_key(idempotency_key):
    return (
        Order.objects
        .select_related(
            "buyer",
            "organization",
            "event",
        )
        .prefetch_related("items")
        .filter(idempotency_key=idempotency_key)
        .first()
    )


def _validate_idempotent_replay(
    *,
    order,
    buyer,
    ticket_lot_id,
    quantity,
):
    """
    Confirma que a chave está sendo repetida com o mesmo conteúdo.

    A mesma chave nunca pode ser reutilizada para:
    - outro comprador;
    - outro lote;
    - outra quantidade.
    """
    if order.buyer_id != buyer.id:
        raise ValidationError(
            {
                "idempotency_key": (
                    "Esta chave de operação não pode ser "
                    "utilizada para esta solicitação."
                )
            }
        )

    existing_items = list(order.items.all())

    if len(existing_items) != 1:
        raise ValidationError(
            {
                "idempotency_key": (
                    "A operação anterior possui uma estrutura "
                    "diferente da solicitação atual."
                )
            }
        )

    existing_item = existing_items[0]

    if (
        existing_item.ticket_lot_id != ticket_lot_id
        or existing_item.quantity != quantity
    ):
        raise ValidationError(
            {
                "idempotency_key": (
                    "A mesma chave não pode ser reutilizada "
                    "com um lote ou quantidade diferente."
                )
            }
        )


@transaction.atomic
def create_reservation_order(
    *,
    buyer,
    ticket_lot_id,
    quantity,
    idempotency_key,
):
    """
    Cria um pedido com reserva temporária de forma idempotente.

    Todas as operações acontecem em uma única transação:
    - valida comprador;
    - bloqueia a chave de idempotência;
    - procura uma execução anterior;
    - bloqueia o lote;
    - recalcula a disponibilidade;
    - congela preço e valores;
    - cria pedido e item.

    Qualquer erro desfaz toda a operação.
    """
    active_buyer = _validated_active_buyer(buyer)

    normalized_idempotency_key = _normalize_uuid(
        value=idempotency_key,
        field_name="idempotency_key",
    )

    normalized_ticket_lot_id = _normalize_uuid(
        value=ticket_lot_id,
        field_name="ticket_lot_id",
    )

    _lock_idempotency_key(
        normalized_idempotency_key
    )

    existing_order = _order_for_idempotency_key(
        normalized_idempotency_key
    )

    if existing_order is not None:
        _validate_idempotent_replay(
            order=existing_order,
            buyer=active_buyer,
            ticket_lot_id=normalized_ticket_lot_id,
            quantity=quantity,
        )

        return OrderCreationResult(
            order=existing_order,
            created=False,
        )

    reference_time = timezone.now()

    availability = (
        lock_ticket_lot_and_calculate_availability(
            ticket_lot_id=normalized_ticket_lot_id,
            at=reference_time,
        )
    )

    validated_quantity = validate_reservation_quantity(
        availability=availability,
        quantity=quantity,
    )

    ticket_lot = availability.ticket_lot
    ticket_type = ticket_lot.ticket_type
    event = ticket_type.event
    organization = event.organization

    unit_price = ticket_lot.price
    item_subtotal = unit_price * validated_quantity

    service_fee = MONEY_ZERO
    order_total = item_subtotal + service_fee

    reservation_expires_at = (
        reference_time
        + timedelta(
            minutes=settings.ORDER_RESERVATION_MINUTES
        )
    )

    order = Order(
        idempotency_key=normalized_idempotency_key,
        buyer=active_buyer,
        organization=organization,
        event=event,
        status=OrderStatus.AWAITING_PAYMENT,
        subtotal=item_subtotal,
        service_fee=service_fee,
        total=order_total,
        reservation_expires_at=reservation_expires_at,
    )

    order.full_clean()
    order.save(force_insert=True)

    order_item = OrderItem(
        order=order,
        ticket_type=ticket_type,
        ticket_lot=ticket_lot,
        quantity=validated_quantity,
        unit_price=unit_price,
        subtotal=item_subtotal,
    )

    order_item.full_clean()
    order_item.save(force_insert=True)

    return OrderCreationResult(
        order=order,
        created=True,
    )

@dataclass(frozen=True, slots=True)
class OrderExpirationResult:
    """
    Resultado da tentativa de expiração de uma reserva.

    expired=True:
        o pedido foi alterado para expirado.

    expired=False:
        o pedido não atendia às condições de expiração.
    """

    order: Order
    expired: bool


@transaction.atomic
def expire_order_reservation(
    *,
    order_id,
    at=None,
):
    """
    Persiste a expiração de uma única reserva.

    O pedido é bloqueado para impedir conflito futuro com uma
    confirmação de pagamento executada simultaneamente.
    """
    normalized_order_id = _normalize_uuid(
        value=order_id,
        field_name="order_id",
    )

    reference_time = at or timezone.now()

    order = (
        Order.objects
        .select_for_update()
        .get(id=normalized_order_id)
    )

    should_expire = (
        order.status == OrderStatus.AWAITING_PAYMENT
        and order.reservation_expires_at is not None
        and order.reservation_expires_at <= reference_time
    )

    if not should_expire:
        return OrderExpirationResult(
            order=order,
            expired=False,
        )

    order.status = OrderStatus.EXPIRED
    order.save(
        update_fields=(
            "status",
            "updated_at",
        )
    )

    return OrderExpirationResult(
        order=order,
        expired=True,
    )


@transaction.atomic
def expire_stale_reservations(
    *,
    at=None,
    batch_size=500,
):
    """
    Persiste reservas vencidas em lotes controlados.

    skip_locked=True permite que mais de um processo trabalhe sem
    selecionar simultaneamente os mesmos pedidos.
    """
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or batch_size <= 0
    ):
        raise ValueError(
            "O tamanho do lote deve ser um número inteiro "
            "maior que zero."
        )

    reference_time = at or timezone.now()

    stale_orders = list(
        Order.objects
        .expired_reservations(at=reference_time)
        .select_for_update(skip_locked=True)
        .order_by(
            "reservation_expires_at",
            "created_at",
        )[:batch_size]
    )

    if not stale_orders:
        return 0

    for order in stale_orders:
        order.status = OrderStatus.EXPIRED
        order.updated_at = reference_time

    Order.objects.bulk_update(
        stale_orders,
        fields=(
            "status",
            "updated_at",
        ),
        batch_size=batch_size,
    )

    return len(stale_orders)