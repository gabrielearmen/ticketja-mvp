from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.marketplace.crypto import decrypt_secret
from apps.marketplace.models import (
    OAuthAuthorizationAttempt,
    PaymentAccountStatus,
)
from apps.marketplace.oauth_client import OAuthTokenResponse
from apps.marketplace.services import (
    OAuthStateError,
    begin_mercado_pago_connection,
    complete_mercado_pago_connection,
)
from apps.organizations.models import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)


TEST_FERNET_KEY = Fernet.generate_key().decode("ascii")


class FakeOAuthClient:
    def __init__(self):
        self.calls = []

    def exchange_authorization_code(self, **kwargs):
        self.calls.append(kwargs)
        return OAuthTokenResponse(
            access_token="seller-access-token",
            refresh_token="seller-refresh-token",
            provider_user_id="987654321",
            expires_in=3600,
            scope="offline_access payments write",
            live_mode=True,
        )


@override_settings(
    MARKETPLACE_OAUTH_ENABLED=True,
    MARKETPLACE_TOKEN_ENCRYPTION_KEYS=TEST_FERNET_KEY,
    MERCADO_PAGO_CLIENT_ID="ticketja-client-id",
    MERCADO_PAGO_CLIENT_SECRET="ticketja-client-secret",
    MERCADO_PAGO_OAUTH_REDIRECT_URI=(
        "https://ticketja.example/painel/recebimentos/mercado-pago/retorno/"
    ),
)
class MarketplaceOAuthServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(
            email="owner@example.com",
            password="Senha-Segura!2026",
        )
        cls.admin_user = get_user_model().objects.create_user(
            email="admin@example.com",
            password="Senha-Segura!2026",
        )
        cls.organization = Organization.objects.create(
            name="Eventos OAuth",
            slug="eventos-oauth",
            status=OrganizationStatus.APPROVED,
        )
        OrganizationMembership.objects.create(
            organization=cls.organization,
            user=cls.owner,
            role=MembershipRole.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=cls.organization,
            user=cls.admin_user,
            role=MembershipRole.ADMIN,
        )

    def test_start_uses_state_digest_and_pkce_s256(self):
        result = begin_mercado_pago_connection(
            organization=self.organization,
            user=self.owner,
        )
        parsed = urlparse(result.authorization_url)
        query = parse_qs(parsed.query)
        raw_state = query["state"][0]
        attempt = OAuthAuthorizationAttempt.objects.get()

        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertNotEqual(attempt.state_digest, raw_state)
        self.assertNotIn(self.owner.email, result.authorization_url)
        self.assertNotIn(
            str(self.organization.id),
            result.authorization_url,
        )

    def test_only_owner_can_start_financial_connection(self):
        with self.assertRaises(PermissionDenied):
            begin_mercado_pago_connection(
                organization=self.organization,
                user=self.admin_user,
            )

    def test_callback_encrypts_tokens_and_cannot_be_replayed(self):
        reference_time = timezone.now()
        started = begin_mercado_pago_connection(
            organization=self.organization,
            user=self.owner,
            at=reference_time,
        )
        raw_state = parse_qs(
            urlparse(started.authorization_url).query
        )["state"][0]
        client = FakeOAuthClient()

        result = complete_mercado_pago_connection(
            state=raw_state,
            code="single-use-code",
            user=self.owner,
            client=client,
            at=reference_time + timedelta(seconds=5),
        )

        account = result.account
        self.assertEqual(account.status, PaymentAccountStatus.ACTIVE)
        self.assertNotIn(
            "seller-access-token",
            account.access_token_ciphertext,
        )
        self.assertEqual(
            decrypt_secret(account.access_token_ciphertext),
            "seller-access-token",
        )
        self.assertEqual(len(client.calls), 1)

        with self.assertRaises(OAuthStateError):
            complete_mercado_pago_connection(
                state=raw_state,
                code="single-use-code",
                user=self.owner,
                client=client,
            )
