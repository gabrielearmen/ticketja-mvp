import json
from urllib.parse import parse_qs
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.marketplace.oauth_client import MercadoPagoOAuthClient


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, limit):
        return self.payload[:limit]


class MercadoPagoOAuthClientTests(SimpleTestCase):
    @override_settings(MERCADO_PAGO_TEST_MODE=True)
    @patch("apps.marketplace.oauth_client.urlopen")
    def test_exchange_sends_pkce_and_parses_seller_identity(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeHttpResponse(
            {
                "access_token": "seller-access",
                "refresh_token": "seller-refresh",
                "user_id": 123456,
                "expires_in": 15552000,
                "scope": "offline_access payments write",
                "live_mode": True,
            }
        )
        client = MercadoPagoOAuthClient(
            client_id="client-id",
            client_secret="client-secret",
            token_url="https://api.mercadopago.com/oauth/token",
            timeout_seconds=10,
        )

        result = client.exchange_authorization_code(
            code="authorization-code",
            state="single-use-state",
            redirect_uri="https://ticketja.example/oauth/return/",
            code_verifier="pkce-verifier",
        )

        request = mocked_urlopen.call_args.args[0]
        payload = parse_qs(request.data.decode("utf-8"))

        self.assertEqual(payload["grant_type"], ["authorization_code"])
        self.assertEqual(payload["code_verifier"], ["pkce-verifier"])
        self.assertEqual(payload["state"], ["single-use-state"])
        self.assertEqual(payload["test_token"], ["true"])
        self.assertEqual(result.provider_user_id, "123456")
        self.assertEqual(result.access_token, "seller-access")

    @override_settings(MERCADO_PAGO_TEST_MODE=False)
    @patch("apps.marketplace.oauth_client.urlopen")
    def test_production_exchange_explicitly_requests_live_token(
        self,
        mocked_urlopen,
    ):
        mocked_urlopen.return_value = FakeHttpResponse(
            {
                "access_token": "seller-access",
                "refresh_token": "seller-refresh",
                "user_id": 123456,
                "expires_in": 15552000,
                "scope": "offline_access payments write",
                "live_mode": True,
            }
        )
        client = MercadoPagoOAuthClient(
            client_id="client-id",
            client_secret="client-secret",
            token_url="https://api.mercadopago.com/oauth/token",
            timeout_seconds=10,
        )

        client.exchange_authorization_code(
            code="authorization-code",
            state="single-use-state",
            redirect_uri="https://ticketja.example/oauth/return/",
            code_verifier="pkce-verifier",
        )

        request = mocked_urlopen.call_args.args[0]
        payload = parse_qs(request.data.decode("utf-8"))

        self.assertEqual(payload["test_token"], ["false"])
