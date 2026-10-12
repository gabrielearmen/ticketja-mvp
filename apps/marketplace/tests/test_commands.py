from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.marketplace.models import FeeBearer, MarketplaceFeePolicy


class ConfigureMarketplaceFeeCommandTests(TestCase):
    def test_command_replaces_active_policy_transactionally(self):
        output = StringIO()

        call_command(
            "configure_marketplace_fee",
            name="Taxa de lançamento",
            percentage="8.00",
            fixed_per_ticket="0.00",
            fee_bearer=FeeBearer.BUYER,
            stdout=output,
        )

        policy = MarketplaceFeePolicy.objects.get(is_active=True)
        self.assertEqual(str(policy.percentage_rate), "8.0000")
        self.assertEqual(str(policy.fixed_amount_per_ticket), "0.00")
        self.assertIn("ativada com sucesso", output.getvalue())
