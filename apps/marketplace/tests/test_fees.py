from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.marketplace.fees import calculate_marketplace_fee
from apps.marketplace.models import FeeBearer, MarketplaceFeePolicy


class MarketplaceFeeCalculationTests(SimpleTestCase):
    def test_buyer_pays_percentage_without_fixed_fee(self):
        policy = MarketplaceFeePolicy(
            percentage_rate=Decimal("8.0000"),
            fixed_amount_per_ticket=Decimal("0.00"),
            fee_bearer=FeeBearer.BUYER,
        )

        quote = calculate_marketplace_fee(
            policy=policy,
            ticket_subtotal=Decimal("100.00"),
            ticket_quantity=2,
        )

        self.assertEqual(quote.platform_fee, Decimal("8.00"))
        self.assertEqual(quote.buyer_total, Decimal("108.00"))
        self.assertEqual(quote.organizer_gross, Decimal("100.00"))

    def test_organizer_can_absorb_percentage_without_increasing_total(self):
        policy = MarketplaceFeePolicy(
            percentage_rate=Decimal("10.0000"),
            fixed_amount_per_ticket=Decimal("0.00"),
            fee_bearer=FeeBearer.ORGANIZER,
        )

        quote = calculate_marketplace_fee(
            policy=policy,
            ticket_subtotal=Decimal("10.00"),
            ticket_quantity=1,
        )

        self.assertEqual(quote.platform_fee, Decimal("1.00"))
        self.assertEqual(quote.buyer_total, Decimal("10.00"))
        self.assertEqual(quote.organizer_gross, Decimal("9.00"))

    def test_policy_outside_commercial_range_is_rejected(self):
        policy = MarketplaceFeePolicy(
            percentage_rate=Decimal("7.9999"),
            fixed_amount_per_ticket=Decimal("0.00"),
            fee_bearer=FeeBearer.BUYER,
        )

        with self.assertRaises(ValidationError):
            calculate_marketplace_fee(
                policy=policy,
                ticket_subtotal=Decimal("100.00"),
                ticket_quantity=1,
            )

    def test_fixed_fee_is_rejected(self):
        policy = MarketplaceFeePolicy(
            percentage_rate=Decimal("8.0000"),
            fixed_amount_per_ticket=Decimal("0.01"),
            fee_bearer=FeeBearer.BUYER,
        )

        with self.assertRaises(ValidationError):
            calculate_marketplace_fee(
                policy=policy,
                ticket_subtotal=Decimal("100.00"),
                ticket_quantity=1,
            )
