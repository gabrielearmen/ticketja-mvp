from django.conf import settings
from django.db.models import Prefetch
from django.utils import timezone

from apps.marketplace.fees import effective_fee_policy
from apps.marketplace.models import (
    OrganizationPaymentAccount,
    PaymentAccountStatus,
)

from .models import TicketLot, TicketType


def commercial_configuration_errors(event):
    """
    Retorna uma lista de impedimentos para publicação.

    A função não altera dados. Ela pode ser utilizada tanto na
    interface quanto no serviço transacional de publicação.
    """
    active_lot_queryset = (
        TicketLot.objects
        .filter(is_active=True)
        .order_by(
            "sales_start",
            "sales_end",
        )
    )

    active_ticket_types = list(
        TicketType.objects
        .filter(
            event=event,
            is_active=True,
        )
        .prefetch_related(
            Prefetch(
                "lots",
                queryset=active_lot_queryset,
                to_attr="active_lots",
            )
        )
        .order_by("name")
    )

    errors = []

    if not active_ticket_types:
        return [
            (
                "Crie pelo menos um tipo de ingresso ativo "
                "antes de publicar."
            )
        ]

    allocated_event_capacity = sum(
        ticket_type.capacity
        for ticket_type in active_ticket_types
    )

    if allocated_event_capacity > event.capacity:
        errors.append(
            (
                "A soma das capacidades dos tipos de ingresso "
                "ultrapassa a capacidade total do evento."
            )
        )

    now = timezone.now()
    has_paid_lot = False

    for ticket_type in active_ticket_types:
        active_lots = ticket_type.active_lots
        has_paid_lot = has_paid_lot or any(
            lot.price > 0
            for lot in active_lots
        )

        if not active_lots:
            errors.append(
                (
                    f'O tipo "{ticket_type.name}" não possui '
                    "um lote ativo."
                )
            )
            continue

        allocated_lot_quantity = sum(
            lot.quantity
            for lot in active_lots
        )

        if allocated_lot_quantity > ticket_type.capacity:
            errors.append(
                (
                    f'A quantidade dos lotes de "{ticket_type.name}" '
                    "ultrapassa a capacidade do tipo."
                )
            )

        previous_lot = None

        for lot in active_lots:
            if lot.sales_start >= lot.sales_end:
                errors.append(
                    (
                        f'O lote "{lot.name}" possui um período '
                        "de vendas inválido."
                    )
                )

            if lot.sales_end <= now:
                errors.append(
                    (
                        f'O lote "{lot.name}" já está encerrado.'
                    )
                )

            if lot.sales_end > event.event_datetime:
                errors.append(
                    (
                        f'O lote "{lot.name}" termina depois da '
                        "realização do evento."
                    )
                )

            if (
                previous_lot is not None
                and lot.sales_start < previous_lot.sales_end
            ):
                errors.append(
                    (
                        f'Os lotes "{previous_lot.name}" e '
                        f'"{lot.name}" possuem períodos '
                        "sobrepostos."
                    )
                )

            previous_lot = lot

    if settings.MARKETPLACE_PAYMENTS_ENABLED and has_paid_lot:
        payment_account_ready = (
            OrganizationPaymentAccount.objects.filter(
                organization=event.organization,
                status=PaymentAccountStatus.ACTIVE,
                provider_user_id__isnull=False,
            )
            .exclude(access_token_ciphertext="")
            .exclude(refresh_token_ciphertext="")
            .exists()
        )

        if not payment_account_ready:
            errors.append(
                "Conecte a conta Mercado Pago da organização antes de publicar um evento pago."
            )

        if effective_fee_policy(at=now) is None:
            errors.append(
                "A política de comissão do TicketJá ainda não foi configurada."
            )

    return errors
