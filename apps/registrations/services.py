import uuid
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.orders.models import (
    Order,
    OrderItem,
    OrderStatus,
)

from .models import Registration


@dataclass(frozen=True, slots=True)
class RegistrationSlotsResult:
    """
    Resultado da criação idempotente dos espaços de inscrição.
    """

    order: Order
    registrations: tuple[Registration, ...]
    created_count: int


def _normalize_uuid(*, value, field_name):
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
    Confirma que o comprador está autenticado, existe e está ativo.
    """
    if (
        not getattr(buyer, "is_authenticated", False)
        or buyer.pk is None
    ):
        raise ValidationError(
            {
                "buyer": (
                    "É necessário entrar em uma conta ativa "
                    "para continuar a inscrição."
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
                    "para continuar a inscrição."
                )
            }
        )

    return active_buyer


def _locked_active_order_for_buyer(
    *,
    order_id,
    buyer,
    at,
):
    """
    Bloqueia o pedido e valida comprador, situação e expiração.

    A mensagem de pedido inexistente e de pedido pertencente a
    outro comprador é propositalmente a mesma. Isso evita revelar
    a existência de pedidos de outras contas.
    """
    order = (
        Order.objects
        .select_for_update()
        .select_related(
            "buyer",
            "organization",
            "event",
        )
        .filter(id=order_id)
        .first()
    )

    if order is None or order.buyer_id != buyer.id:
        raise ValidationError(
            {
                "order": (
                    "Pedido indisponível para esta operação."
                )
            }
        )

    if order.status != OrderStatus.AWAITING_PAYMENT:
        raise ValidationError(
            {
                "order": (
                    "Somente reservas aguardando pagamento "
                    "podem receber os dados dos participantes."
                )
            }
        )

    if (
        order.reservation_expires_at is None
        or order.reservation_expires_at <= at
    ):
        raise ValidationError(
            {
                "order": (
                    "O prazo da reserva terminou. "
                    "Inicie uma nova inscrição."
                )
            }
        )

    return order


@transaction.atomic
def ensure_registration_slots(
    *,
    order_id,
    buyer,
    at=None,
):
    """
    Garante uma inscrição para cada ingresso reservado.

    O serviço é transacional e idempotente:
    - bloqueia o pedido;
    - confirma o comprador;
    - confirma que a reserva continua válida;
    - bloqueia os itens e inscrições existentes;
    - preserva registros já criados;
    - cria somente os registros ausentes;
    - recusa posições superiores à quantidade comprada.
    """
    active_buyer = _validated_active_buyer(buyer)

    normalized_order_id = _normalize_uuid(
        value=order_id,
        field_name="order_id",
    )

    reference_time = at or timezone.now()

    order = _locked_active_order_for_buyer(
        order_id=normalized_order_id,
        buyer=active_buyer,
        at=reference_time,
    )

    order_items = list(
        OrderItem.objects
        .select_for_update()
        .filter(order=order)
        .order_by(
            "created_at",
            "id",
        )
    )

    if not order_items:
        raise ValidationError(
            {
                "order": (
                    "O pedido não possui ingressos reservados."
                )
            }
        )

    existing_registrations = list(
        Registration.objects
        .select_for_update()
        .filter(order_item__order=order)
        .order_by(
            "order_item_id",
            "position",
        )
    )

    expected_positions = {
        (order_item.id, position)
        for order_item in order_items
        for position in range(
            1,
            order_item.quantity + 1,
        )
    }

    existing_by_position = {
        (
            registration.order_item_id,
            registration.position,
        ): registration
        for registration in existing_registrations
    }

    unexpected_positions = (
        set(existing_by_position)
        - expected_positions
    )

    if unexpected_positions:
        raise ValidationError(
            {
                "order": (
                    "As inscrições deste pedido estão "
                    "inconsistentes com a quantidade comprada."
                )
            }
        )

    missing_positions = sorted(
        expected_positions - set(existing_by_position),
        key=lambda value: (
            str(value[0]),
            value[1],
        ),
    )

    missing_registrations = [
        Registration(
            order_item_id=order_item_id,
            position=position,
        )
        for order_item_id, position in missing_positions
    ]

    if missing_registrations:
        Registration.objects.bulk_create(
            missing_registrations
        )

    registrations = tuple(
        Registration.objects
        .filter(order_item__order=order)
        .select_related(
            "order_item",
            "order_item__order",
            "order_item__ticket_type",
            "order_item__ticket_lot",
        )
        .order_by(
            "order_item__created_at",
            "position",
        )
    )

    expected_count = sum(
        order_item.quantity
        for order_item in order_items
    )

    if len(registrations) != expected_count:
        raise ValidationError(
            {
                "order": (
                    "Não foi possível preparar todas as "
                    "inscrições do pedido."
                )
            }
        )

    return RegistrationSlotsResult(
        order=order,
        registrations=registrations,
        created_count=len(missing_registrations),
    )