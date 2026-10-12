from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import (
    COMMERCIAL_PERCENT_MAX,
    COMMERCIAL_PERCENT_MIN,
    FeeBearer,
    MarketplaceFeePolicy,
    MONEY_ZERO,
)


CENT = Decimal("0.01")
HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class MarketplaceFeeQuote:
    policy_id: object
    fee_bearer: str
    ticket_subtotal: Decimal
    ticket_quantity: int
    platform_fee: Decimal
    buyer_total: Decimal
    organizer_gross: Decimal


def effective_fee_policy(*, at=None, for_update=False):
    reference_time = at or timezone.now()
    policies = MarketplaceFeePolicy.objects.filter(
        is_active=True,
        effective_from__lte=reference_time,
    ).filter(
        Q(effective_until__isnull=True)
        | Q(effective_until__gt=reference_time)
    )

    if for_update:
        policies = policies.select_for_update()

    return policies.order_by("-effective_from").first()


def calculate_marketplace_fee(
    *,
    policy: MarketplaceFeePolicy,
    ticket_subtotal,
    ticket_quantity,
):
    if not (
        COMMERCIAL_PERCENT_MIN
        <= policy.percentage_rate
        <= COMMERCIAL_PERCENT_MAX
    ):
        raise ValidationError(
            "A política de comissão deve estar entre 8% e 10%."
        )

    if policy.fixed_amount_per_ticket != MONEY_ZERO:
        raise ValidationError(
            "A política comercial não permite cobrança fixa por ingresso."
        )

    if policy.minimum_fee is not None or policy.maximum_fee is not None:
        raise ValidationError(
            "A política comercial não permite valores mínimo ou máximo."
        )

    subtotal = Decimal(str(ticket_subtotal)).quantize(CENT)

    if subtotal < 0:
        raise ValidationError("O subtotal não pode ser negativo.")

    if not isinstance(ticket_quantity, int) or ticket_quantity <= 0:
        raise ValidationError(
            "A quantidade de inscrições deve ser maior que zero."
        )

    percentage_component = (
        subtotal
        * Decimal(str(policy.percentage_rate))
        / HUNDRED
    )
    platform_fee = percentage_component.quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )

    if (
        policy.fee_bearer == FeeBearer.ORGANIZER
        and platform_fee > subtotal
    ):
        raise ValidationError(
            "A comissão não pode superar o valor dos ingressos."
        )

    buyer_total = subtotal
    organizer_gross = subtotal

    if policy.fee_bearer == FeeBearer.BUYER:
        buyer_total += platform_fee
    else:
        organizer_gross -= platform_fee

    return MarketplaceFeeQuote(
        policy_id=policy.id,
        fee_bearer=policy.fee_bearer,
        ticket_subtotal=subtotal,
        ticket_quantity=ticket_quantity,
        platform_fee=platform_fee,
        buyer_total=buyer_total.quantize(CENT),
        organizer_gross=organizer_gross.quantize(CENT),
    )
