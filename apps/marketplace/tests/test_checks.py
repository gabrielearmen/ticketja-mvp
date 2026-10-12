from cryptography.fernet import Fernet
from django.test import SimpleTestCase, override_settings

from apps.marketplace.checks import marketplace_configuration_check


class MarketplaceConfigurationCheckTests(SimpleTestCase):
    @override_settings(
        MARKETPLACE_PAYMENTS_ENABLED=True,
        MARKETPLACE_OAUTH_ENABLED=False,
        MARKETPLACE_TOKEN_ENCRYPTION_KEYS=(
            Fernet.generate_key().decode("ascii")
        ),
        MERCADO_PAGO_CLIENT_ID="client-id",
        MERCADO_PAGO_CLIENT_SECRET="client-secret",
        MERCADO_PAGO_OAUTH_REDIRECT_URI="https://ticketja.example/oauth/",
        MERCADO_PAGO_WEBHOOK_SECRET="",
    )
    def test_real_payments_require_oauth_and_webhook_secret(self):
        error_ids = {
            error.id
            for error in marketplace_configuration_check(None)
        }

        self.assertIn("marketplace.E004", error_ids)
        self.assertIn("marketplace.E005", error_ids)

    @override_settings(
        MARKETPLACE_PAYMENTS_ENABLED=True,
        MARKETPLACE_OAUTH_ENABLED=True,
        MARKETPLACE_TOKEN_ENCRYPTION_KEYS=(
            Fernet.generate_key().decode("ascii")
        ),
        MERCADO_PAGO_CLIENT_ID="client-id",
        MERCADO_PAGO_CLIENT_SECRET="client-secret",
        MERCADO_PAGO_OAUTH_REDIRECT_URI="https://ticketja.example/oauth/",
        MERCADO_PAGO_WEBHOOK_SECRET="webhook-secret",
        MERCADO_PAGO_API_BASE_URL="https://api.mercadopago.com",
    )
    def test_complete_marketplace_configuration_passes(self):
        self.assertEqual(
            marketplace_configuration_check(None),
            [],
        )
