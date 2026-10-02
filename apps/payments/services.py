from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.kits.models import (
    RegistrationKitSelection,
    TicketTypeKit,
)
from apps.orders.models import (
    Order,
    OrderItem,
    OrderStatus,
)
from apps.registrations.models import Registration

from .gateways.base import (
    PaymentGatewayConfigurationError,
    PaymentGatewayError,
    PaymentGatewayRejectedError,
    PaymentGatewayTemporaryError,
    PixChargeRequest,
)
from .gateways.registry import get_payment_gateway
from .models import (
    OPEN_PAYMENT_STATUSES,
    Payment,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
)


MONEY_ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class PaymentInitiationResult:
    order: Order
    payment: Payment
    created: bool
    is_free: bool


@dataclass(frozen=True, slots=True)
class _PreparedPayment:
    order: Order
    payment: Payment
    created: bool
    requires_gateway: bool


def _validation_error(message):
    return ValidationError(
        {
            "payment": message,
        }
    )


def _validate_buyer(buyer):
    if (
        not getattr(buyer, "is_authenticated", False)
        or buyer.pk is None
        or not buyer.is_active
    ):
        raise _validation_error(
            "É necessário entrar em uma conta ativa "
            "para realizar o pagamento."
        )


def _validate_checkout_completeness(order):
    """
    Confirma que existe exatamente uma inscrição completa para
    cada ingresso e que todos os kits obrigatórios foram escolhidos.
    """
    order_items = list(
        OrderItem.objects
        .select_for_update()
        .filter(order=order)
        .order_by("created_at", "id")
    )

    if not order_items:
        raise _validation_error(
            "O pedido não possui ingressos."
        )

    expected_registration_count = sum(
        item.quantity
        for item in order_items
    )

    registrations = list(
        Registration.objects
        .select_for_update()
        .select_related(
            "order_item",
            "order_item__ticket_type",
        )
        .filter(order_item__order=order)
        .order_by(
            "order_item__created_at",
            "position",
        )
    )

    if len(registrations) != expected_registration_count:
        raise _validation_error(
            "Cadastre uma pessoa para cada ingresso antes "
            "de iniciar o pagamento."
        )

    incomplete_registrations = [
        registration
        for registration in registrations
        if not registration.is_complete
    ]

    if incomplete_registrations:
        raise _validation_error(
            "Conclua os dados de todos os participantes "
            "antes de iniciar o pagamento."
        )

    ticket_type_ids = {
        registration.order_item.ticket_type_id
        for registration in registrations
    }

    required_assignments = list(
        TicketTypeKit.objects
        .select_for_update()
        .select_related("kit")
        .filter(
            ticket_type_id__in=ticket_type_ids,
            kit__is_active=True,
            kit__is_required=True,
        )
    )

    required_kits_by_ticket_type = {}

    for assignment in required_assignments:
        required_kits_by_ticket_type.setdefault(
            assignment.ticket_type_id,
            set(),
        ).add(assignment.kit_id)

    selection_pairs = set(
        RegistrationKitSelection.objects
        .select_for_update()
        .filter(
            registration_id__in=[
                registration.id
                for registration in registrations
            ]
        )
        .values_list(
            "registration_id",
            "kit_id",
        )
    )

    for registration in registrations:
        required_kit_ids = (
            required_kits_by_ticket_type.get(
                registration.order_item.ticket_type_id,
                set(),
            )
        )

        for kit_id in required_kit_ids:
            if (
                registration.id,
                kit_id,
            ) not in selection_pairs:
                raise _validation_error(
                    "Selecione todos os kits obrigatórios "
                    "antes de iniciar o pagamento."
                )


def _next_attempt_number(payments):
    if not payments:
        return 1

    return max(
        payment.attempt_number
        for payment in payments
    ) + 1


@transaction.atomic
def _prepare_payment(
    *,
    order_id,
    buyer,
    at,
):
    _validate_buyer(buyer)

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
        raise _validation_error(
            "Pedido indisponível para esta operação."
        )

    payments = list(
        Payment.objects
        .select_for_update()
        .filter(order=order)
        .order_by("attempt_number")
    )

    approved_payment = next(
        (
            payment
            for payment in payments
            if payment.status == PaymentStatus.APPROVED
        ),
        None,
    )

    if order.status == OrderStatus.PAID:
        if approved_payment is None:
            raise _validation_error(
                "O pedido está pago, mas o registro do "
                "pagamento precisa ser conciliado."
            )

        return _PreparedPayment(
            order=order,
            payment=approved_payment,
            created=False,
            requires_gateway=False,
        )

    if order.status != OrderStatus.AWAITING_PAYMENT:
        raise _validation_error(
            "Este pedido não está disponível para pagamento."
        )

    if (
        order.reservation_expires_at is None
        or order.reservation_expires_at <= at
    ):
        raise _validation_error(
            "O prazo da reserva terminou. "
            "Inicie uma nova inscrição."
        )

    _validate_checkout_completeness(order)

    open_payment = next(
        (
            payment
            for payment in payments
            if payment.status in OPEN_PAYMENT_STATUSES
        ),
        None,
    )

    if order.total == MONEY_ZERO:
        if open_payment is not None:
            raise _validation_error(
                "Existe uma tentativa de pagamento incompatível "
                "com este pedido gratuito."
            )

        approved_at = at

        payment = Payment(
            order=order,
            attempt_number=_next_attempt_number(
                payments
            ),
            provider=PaymentProvider.INTERNAL,
            method=PaymentMethod.FREE,
            status=PaymentStatus.APPROVED,
            amount=MONEY_ZERO,
            platform_fee=MONEY_ZERO,
            approved_at=approved_at,
        )

        payment.full_clean()
        payment.save(force_insert=True)

        order.status = OrderStatus.PAID
        order.save(
            update_fields=(
                "status",
                "updated_at",
            )
        )

        return _PreparedPayment(
            order=order,
            payment=payment,
            created=True,
            requires_gateway=False,
        )

    requested_pix_expiration = (
        at
        + timedelta(
            minutes=(
                settings.PAYMENT_PIX_EXPIRATION_MINUTES
            )
        )
    )

    payment_created = False

    if open_payment is None:
        pix_expiration = requested_pix_expiration

        payment = Payment(
            order=order,
            attempt_number=_next_attempt_number(
                payments
            ),
            provider=PaymentProvider.MERCADO_PAGO,
            method=PaymentMethod.PIX,
            status=PaymentStatus.CREATED,
            amount=order.total,
            platform_fee=MONEY_ZERO,
            expires_at=pix_expiration,
        )

        payment.full_clean()
        payment.save(force_insert=True)
        payment_created = True
    else:
        payment = open_payment

        if (
            payment.provider
            != PaymentProvider.MERCADO_PAGO
            or payment.method != PaymentMethod.PIX
        ):
            raise _validation_error(
                "Já existe uma tentativa de pagamento "
                "incompatível para este pedido."
            )

        if payment.expires_at is None:
            raise _validation_error(
                "A tentativa PIX existente não possui "
                "um vencimento válido."
            )

        # Uma repetição precisa manter o vencimento original.
        # Isso preserva o mesmo conteúdo enviado com a mesma
        # chave de idempotência.
        pix_expiration = payment.expires_at

    if order.reservation_expires_at != pix_expiration:
        order.reservation_expires_at = pix_expiration
        order.save(
            update_fields=(
                "reservation_expires_at",
                "updated_at",
            )
        )

    already_has_pix = (
        payment.status == PaymentStatus.PENDING
        and bool(payment.provider_order_id)
        and bool(payment.provider_payment_id)
        and bool(payment.pix_copy_paste)
        and bool(payment.pix_qr_code_base64)
    )

    return _PreparedPayment(
        order=order,
        payment=payment,
        created=payment_created,
        requires_gateway=not already_has_pix,
    )


@transaction.atomic
def _record_gateway_failure(
    *,
    payment_id,
    code,
    message,
    terminal,
):
    payment = (
        Payment.objects
        .select_for_update()
        .get(id=payment_id)
    )

    if payment.status not in OPEN_PAYMENT_STATUSES:
        return

    payment.failure_code = str(code)[:100]
    payment.failure_message = str(message)[:500]

    update_fields = [
        "failure_code",
        "failure_message",
        "updated_at",
    ]

    if terminal:
        payment.status = PaymentStatus.ERROR
        update_fields.append("status")

    payment.save(update_fields=tuple(update_fields))


@transaction.atomic
def _save_pix_result(
    *,
    payment_id,
    pix_result,
    created,
):
    payment = (
        Payment.objects
        .select_for_update()
        .select_related("order")
        .get(id=payment_id)
    )

    order = (
        Order.objects
        .select_for_update()
        .get(id=payment.order_id)
    )

    if (
        payment.status == PaymentStatus.PENDING
        and payment.pix_copy_paste
        and payment.pix_qr_code_base64
    ):
        return PaymentInitiationResult(
            order=order,
            payment=payment,
            created=False,
            is_free=False,
        )

    if payment.status != PaymentStatus.CREATED:
        raise _validation_error(
            "Esta tentativa de pagamento não pode mais "
            "receber uma cobrança PIX."
        )

    if order.status != OrderStatus.AWAITING_PAYMENT:
        raise _validation_error(
            "O pedido não está mais aguardando pagamento."
        )

    payment.provider_order_id = (
        pix_result.provider_order_id
    )
    payment.provider_payment_id = (
        pix_result.provider_payment_id
    )
    payment.provider_status = (
        pix_result.provider_status
    )
    payment.provider_status_detail = (
        pix_result.provider_status_detail
    )
    payment.pix_copy_paste = (
        pix_result.pix_copy_paste
    )
    payment.pix_qr_code_base64 = (
        pix_result.pix_qr_code_base64
    )
    payment.checkout_url = pix_result.checkout_url
    payment.expires_at = pix_result.expires_at
    payment.status = PaymentStatus.PENDING
    payment.failure_code = ""
    payment.failure_message = ""

    payment.full_clean()
    payment.save(
        update_fields=(
            "provider_order_id",
            "provider_payment_id",
            "provider_status",
            "provider_status_detail",
            "pix_copy_paste",
            "pix_qr_code_base64",
            "checkout_url",
            "expires_at",
            "status",
            "failure_code",
            "failure_message",
            "updated_at",
        )
    )

    return PaymentInitiationResult(
        order=order,
        payment=payment,
        created=created,
        is_free=False,
    )


def initiate_order_payment(
    *,
    order_id,
    buyer,
    gateway=None,
    at=None,
):
    """
    Inicia o pagamento de forma idempotente.

    O banco não permanece bloqueado durante a chamada de rede.
    Primeiro criamos a tentativa e salvamos sua chave. Depois
    chamamos o provedor e, por fim, persistimos a resposta.
    """
    reference_time = at or timezone.now()

    prepared = _prepare_payment(
        order_id=order_id,
        buyer=buyer,
        at=reference_time,
    )

    if not prepared.requires_gateway:
        return PaymentInitiationResult(
            order=prepared.order,
            payment=prepared.payment,
            created=prepared.created,
            is_free=(
                prepared.payment.method
                == PaymentMethod.FREE
            ),
        )

    selected_gateway = gateway or get_payment_gateway()

    pix_request = PixChargeRequest(
        payment_id=prepared.payment.id,
        idempotency_key=(
            prepared.payment.idempotency_key
        ),
        external_reference=(
            prepared.payment.external_reference
        ),
        description=(
            f"Pedido {prepared.order.public_code} - "
            f"{prepared.order.event.title}"
        )[:255],
        amount=prepared.payment.amount,
        platform_fee=prepared.payment.platform_fee,
        payer_email=prepared.order.buyer.email,
        expires_at=prepared.payment.expires_at,
        expiration_seconds=(
            settings.PAYMENT_PIX_EXPIRATION_MINUTES
            * 60
        ),
        provider_account_reference=(
            prepared.payment
            .provider_account_reference
        ),
    )

    try:
        pix_result = selected_gateway.create_pix_charge(
            pix_request
        )

    except PaymentGatewayTemporaryError as error:
        _record_gateway_failure(
            payment_id=prepared.payment.id,
            code="temporary_provider_error",
            message=error,
            terminal=False,
        )
        raise

    except PaymentGatewayRejectedError as error:
        _record_gateway_failure(
            payment_id=prepared.payment.id,
            code="provider_rejected",
            message=error,
            terminal=True,
        )
        raise

    except PaymentGatewayConfigurationError as error:
        _record_gateway_failure(
            payment_id=prepared.payment.id,
            code="provider_configuration",
            message=error,
            terminal=False,
        )
        raise

    except PaymentGatewayError as error:
        _record_gateway_failure(
            payment_id=prepared.payment.id,
            code="provider_error",
            message=error,
            terminal=False,
        )
        raise

    return _save_pix_result(
        payment_id=prepared.payment.id,
        pix_result=pix_result,
        created=prepared.created,
    )