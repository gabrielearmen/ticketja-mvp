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
from apps.marketplace.models import (
    OrganizationPaymentAccount,
    PaymentAccountStatus,
)
from apps.marketplace.crypto import (
    SecretDecryptionError,
    decrypt_secret,
    encrypt_secret,
)
from apps.orders.models import (
    Order,
    OrderItem,
    OrderStatus,
)
from apps.registrations.models import Registration
from apps.registrations.validators import validate_cpf

from .gateways.base import (
    HostedCheckoutItem,
    HostedCheckoutRequest,
    PaymentGatewayConfigurationError,
    PaymentGatewayError,
    PaymentGatewayRejectedError,
    PaymentGatewayTemporaryError,
    PixChargeRequest,
)
from .gateways.registry import (
    get_payment_gateway,
    get_payment_gateway_for_organization,
)
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


@dataclass(frozen=True, slots=True)
class PayerDetails:
    email: str
    first_name: str
    last_name: str
    document_type: str
    document_number: str


@dataclass(frozen=True, slots=True)
class CheckoutReturnUrls:
    success: str
    pending: str
    failure: str


def _uses_hosted_checkout():
    return (
        settings.MARKETPLACE_PAYMENTS_ENABLED
        and settings.MARKETPLACE_CHECKOUT_MODE
        == "checkout_pro"
    )


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


def _normalize_payer_details(*, buyer, payer_data):
    if payer_data is None:
        return None

    first_name = " ".join(
        str(payer_data.get("first_name") or "").split()
    )
    last_name = " ".join(
        str(payer_data.get("last_name") or "").split()
    )
    document_type = str(
        payer_data.get("document_type") or ""
    ).strip().upper()

    if not first_name or not last_name:
        raise _validation_error(
            "Informe o nome completo do pagador."
        )

    if document_type != "CPF":
        raise _validation_error(
            "O pagamento PIX exige um CPF válido do pagador."
        )

    try:
        document_number = validate_cpf(
            payer_data.get("document_number")
        )
    except ValidationError as error:
        raise _validation_error(
            "Informe um CPF válido do pagador."
        ) from error

    return PayerDetails(
        email=str(buyer.email).strip().lower(),
        first_name=first_name,
        last_name=last_name,
        document_type=document_type,
        document_number=document_number,
    )


def _payment_has_same_payer(*, payment, payer):
    try:
        persisted_document = decrypt_secret(
            payment.payer_document_ciphertext
        )
    except SecretDecryptionError as error:
        raise _validation_error(
            "Não foi possível recuperar os dados protegidos do pagador."
        ) from error

    return (
        payment.payer_email == payer.email
        and payment.payer_first_name == payer.first_name
        and payment.payer_last_name == payer.last_name
        and payment.payer_document_type == payer.document_type
        and persisted_document == payer.document_number
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
    payer_data,
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

    payer = _normalize_payer_details(
        buyer=buyer,
        payer_data=payer_data,
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

    if (
        settings.MARKETPLACE_PAYMENTS_ENABLED
        and not _uses_hosted_checkout()
        and payer is None
    ):
        raise _validation_error(
            "Informe os dados do pagador antes de gerar o PIX."
        )

    expiration_minutes = (
        settings.PAYMENT_CHECKOUT_EXPIRATION_MINUTES
        if _uses_hosted_checkout()
        else settings.PAYMENT_PIX_EXPIRATION_MINUTES
    )
    requested_expiration = (
        at
        + timedelta(
            minutes=expiration_minutes
        )
    )

    payment_created = False

    if open_payment is None:
        payment_expiration = requested_expiration
        provider_account_reference = ""

        if settings.MARKETPLACE_PAYMENTS_ENABLED:
            if (
                order.subtotal > MONEY_ZERO
                and order.fee_policy_reference is None
            ):
                raise _validation_error(
                    "Este pedido foi criado antes da configuração financeira. "
                    "Inicie uma nova inscrição."
                )

            payment_account = (
                OrganizationPaymentAccount.objects
                .select_for_update()
                .filter(
                    organization=order.organization,
                    status=PaymentAccountStatus.ACTIVE,
                )
                .first()
            )

            if payment_account is None or not payment_account.is_usable:
                raise _validation_error(
                    "O organizador ainda não habilitou o recebimento deste evento."
                )

            provider_account_reference = (
                payment_account.provider_user_id
            )

        payment = Payment(
            order=order,
            attempt_number=_next_attempt_number(
                payments
            ),
            provider=PaymentProvider.MERCADO_PAGO,
            method=(
                PaymentMethod.CHECKOUT_PRO
                if _uses_hosted_checkout()
                else PaymentMethod.PIX
            ),
            status=PaymentStatus.CREATED,
            amount=order.total,
            platform_fee=order.platform_fee,
            payer_email=(payer.email if payer else buyer.email),
            payer_first_name=(payer.first_name if payer else ""),
            payer_last_name=(payer.last_name if payer else ""),
            payer_document_type=(
                payer.document_type if payer else ""
            ),
            payer_document_ciphertext=(
                encrypt_secret(payer.document_number)
                if payer
                else ""
            ),
            payer_document_last4=(
                payer.document_number[-4:] if payer else ""
            ),
            provider_account_reference=(
                provider_account_reference
            ),
            expires_at=payment_expiration,
        )

        payment.full_clean()
        payment.save(force_insert=True)
        payment_created = True
    else:
        payment = open_payment

        if (
            settings.MARKETPLACE_PAYMENTS_ENABLED
            and not payment.payer_document_ciphertext
        ):
            raise _validation_error(
                "Esta tentativa não possui os dados protegidos do pagador. "
                "Inicie uma nova inscrição."
            )

        if (
            payer is not None
            and not _payment_has_same_payer(
                payment=payment,
                payer=payer,
            )
        ):
            raise _validation_error(
                "Os dados do pagador não podem ser alterados depois que "
                "a tentativa de pagamento foi criada."
            )

        if (
            payment.provider
            != PaymentProvider.MERCADO_PAGO
            or payment.method
            not in {
                PaymentMethod.PIX,
                PaymentMethod.CHECKOUT_PRO,
            }
        ):
            raise _validation_error(
                "Já existe uma tentativa de pagamento "
                "incompatível para este pedido."
            )

        if payment.expires_at is None:
            raise _validation_error(
                "A tentativa de pagamento existente não possui "
                "um vencimento válido."
            )

        # Uma repetição precisa manter o vencimento original.
        # Isso preserva o mesmo conteúdo enviado com a mesma
        # chave de idempotência.
        payment_expiration = payment.expires_at

    if order.reservation_expires_at != payment_expiration:
        order.reservation_expires_at = payment_expiration
        order.save(
            update_fields=(
                "reservation_expires_at",
                "updated_at",
            )
        )

    already_has_pix = (
        payment.status == PaymentStatus.PENDING
        and payment.method == PaymentMethod.PIX
        and bool(payment.provider_order_id)
        and bool(payment.provider_payment_id)
        and bool(payment.pix_copy_paste)
        and bool(payment.checkout_url)
    )

    already_has_hosted_checkout = (
        payment.status == PaymentStatus.PENDING
        and payment.method == PaymentMethod.CHECKOUT_PRO
        and bool(payment.provider_order_id)
        and bool(payment.checkout_url)
    )

    return _PreparedPayment(
        order=order,
        payment=payment,
        created=payment_created,
        requires_gateway=not (
            already_has_pix
            or already_has_hosted_checkout
        ),
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


def _hosted_checkout_items(order):
    items = [
        HostedCheckoutItem(
            title=(
                f"{item.ticket_type.name} — "
                f"{order.event.title}"
            ),
            quantity=item.quantity,
            unit_price=item.unit_price,
        )
        for item in (
            order.items
            .select_related("ticket_type")
            .order_by("created_at", "id")
        )
    ]

    if order.service_fee > MONEY_ZERO:
        items.append(
            HostedCheckoutItem(
                title="Taxa de serviço TicketJá",
                quantity=1,
                unit_price=order.service_fee,
            )
        )

    return tuple(items)


@transaction.atomic
def _save_hosted_checkout_result(
    *,
    payment_id,
    checkout_result,
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
        and payment.provider_order_id
        and payment.checkout_url
    ):
        return PaymentInitiationResult(
            order=order,
            payment=payment,
            created=False,
            is_free=False,
        )

    if (
        payment.status != PaymentStatus.CREATED
        or payment.method != PaymentMethod.CHECKOUT_PRO
    ):
        raise _validation_error(
            "Esta tentativa não pode mais receber uma sessão de checkout."
        )

    if order.status != OrderStatus.AWAITING_PAYMENT:
        raise _validation_error(
            "O pedido não está mais aguardando pagamento."
        )

    payment.provider_order_id = (
        checkout_result.provider_order_id
    )
    payment.provider_status = checkout_result.provider_status
    payment.provider_status_detail = (
        checkout_result.provider_status_detail
    )
    payment.checkout_url = checkout_result.checkout_url
    payment.expires_at = checkout_result.expires_at
    payment.status = PaymentStatus.PENDING
    payment.failure_code = ""
    payment.failure_message = ""

    payment.full_clean()
    payment.save(
        update_fields=(
            "provider_order_id",
            "provider_status",
            "provider_status_detail",
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
    payer_data=None,
    return_urls=None,
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
        payer_data=payer_data,
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

    selected_gateway = gateway

    if selected_gateway is None:
        if settings.MARKETPLACE_PAYMENTS_ENABLED:
            selected_gateway = (
                get_payment_gateway_for_organization(
                    prepared.order.organization,
                    use_orders_api=(
                        prepared.payment.method
                        == PaymentMethod.CHECKOUT_PRO
                    ),
                )
            )
        else:
            selected_gateway = get_payment_gateway()

    if prepared.payment.method == PaymentMethod.CHECKOUT_PRO:
        if not isinstance(return_urls, CheckoutReturnUrls):
            raise _validation_error(
                "As URLs seguras de retorno do checkout não foram informadas."
            )

        checkout_request = HostedCheckoutRequest(
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
            payer_email=(
                prepared.payment.payer_email
                or prepared.order.buyer.email
            ),
            expires_at=prepared.payment.expires_at,
            expiration_seconds=(
                settings.PAYMENT_CHECKOUT_EXPIRATION_MINUTES
                * 60
            ),
            success_url=return_urls.success,
            pending_url=return_urls.pending,
            failure_url=return_urls.failure,
            items=_hosted_checkout_items(prepared.order),
            provider_account_reference=(
                prepared.payment.provider_account_reference
            ),
        )

        try:
            checkout_result = (
                selected_gateway.create_hosted_checkout(
                    checkout_request
                )
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

        return _save_hosted_checkout_result(
            payment_id=prepared.payment.id,
            checkout_result=checkout_result,
            created=prepared.created,
        )

    payer_document_number = ""

    if prepared.payment.payer_document_ciphertext:
        try:
            payer_document_number = decrypt_secret(
                prepared.payment.payer_document_ciphertext
            )
        except SecretDecryptionError as error:
            raise _validation_error(
                "Não foi possível recuperar os dados protegidos do pagador."
            ) from error

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
        payer_email=(
            prepared.payment.payer_email
            or prepared.order.buyer.email
        ),
        expires_at=prepared.payment.expires_at,
        expiration_seconds=(
            settings.PAYMENT_PIX_EXPIRATION_MINUTES
            * 60
        ),
        provider_account_reference=(
            prepared.payment
            .provider_account_reference
        ),
        payer_first_name=prepared.payment.payer_first_name,
        payer_last_name=prepared.payment.payer_last_name,
        payer_document_type=(
            prepared.payment.payer_document_type
        ),
        payer_document_number=payer_document_number,
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
