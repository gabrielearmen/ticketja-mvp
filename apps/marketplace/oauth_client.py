import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from django.conf import settings


MAX_OAUTH_RESPONSE_BYTES = 1024 * 1024


class OAuthClientError(Exception):
    """Erro base da comunicação OAuth."""


class OAuthClientConfigurationError(OAuthClientError):
    """A integração não possui configuração válida."""


class OAuthClientRejectedError(OAuthClientError):
    """O provedor recusou definitivamente a solicitação."""


class OAuthClientTemporaryError(OAuthClientError):
    """Falha temporária que permite uma nova autorização."""


@dataclass(frozen=True, slots=True)
class OAuthTokenResponse:
    access_token: str
    refresh_token: str
    provider_user_id: str
    expires_in: int
    scope: str
    live_mode: bool | None


class MercadoPagoOAuthClient:
    def __init__(
        self,
        *,
        client_id=None,
        client_secret=None,
        token_url=None,
        timeout_seconds=None,
    ):
        self.client_id = str(
            client_id
            if client_id is not None
            else settings.MERCADO_PAGO_CLIENT_ID
        ).strip()
        self.client_secret = str(
            client_secret
            if client_secret is not None
            else settings.MERCADO_PAGO_CLIENT_SECRET
        ).strip()
        self.token_url = str(
            token_url
            if token_url is not None
            else settings.MERCADO_PAGO_OAUTH_TOKEN_URL
        ).strip()
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.MERCADO_PAGO_TIMEOUT_SECONDS
        )

        if not self.client_id or not self.client_secret:
            raise OAuthClientConfigurationError(
                "As credenciais OAuth do Mercado Pago não foram configuradas."
            )

        parsed_url = urlparse(self.token_url)

        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise OAuthClientConfigurationError(
                "O endpoint OAuth do Mercado Pago deve usar HTTPS."
            )

    def _post_form(self, payload):
        request = Request(
            url=self.token_url,
            data=urlencode(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                raw_body = response.read(
                    MAX_OAUTH_RESPONSE_BYTES + 1
                )
        except HTTPError as error:
            if error.code == 429 or error.code >= 500:
                raise OAuthClientTemporaryError(
                    "O Mercado Pago está temporariamente indisponível."
                ) from error

            raise OAuthClientRejectedError(
                "O Mercado Pago recusou a autorização. Inicie uma nova conexão."
            ) from error
        except (URLError, TimeoutError) as error:
            raise OAuthClientTemporaryError(
                "Não foi possível concluir a conexão com o Mercado Pago."
            ) from error

        if len(raw_body) > MAX_OAUTH_RESPONSE_BYTES:
            raise OAuthClientTemporaryError(
                "O Mercado Pago retornou uma resposta acima do limite seguro."
            )

        try:
            parsed_body = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OAuthClientTemporaryError(
                "O Mercado Pago retornou uma resposta inválida."
            ) from error

        if not isinstance(parsed_body, dict):
            raise OAuthClientTemporaryError(
                "O Mercado Pago retornou uma resposta inesperada."
            )

        return parsed_body

    def exchange_authorization_code(
        self,
        *,
        code,
        state,
        redirect_uri,
        code_verifier,
    ):
        request_payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": str(code),
            "redirect_uri": str(redirect_uri),
            "state": str(state),
            "code_verifier": str(code_verifier),
        }

        # O Mercado Pago exige este parâmetro na troca inicial do
        # código OAuth para emitir credenciais sandbox do vendedor.
        request_payload["test_token"] = (
            "true"
            if settings.MERCADO_PAGO_TEST_MODE
            else "false"
        )

        payload = self._post_form(request_payload)

        return self._parse_token_response(payload)

    def refresh_access_token(self, *, refresh_token):
        payload = self._post_form(
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": str(refresh_token),
            }
        )

        return self._parse_token_response(payload)

    def _parse_token_response(self, payload):
        access_token = str(
            payload.get("access_token") or ""
        ).strip()
        refresh_token = str(
            payload.get("refresh_token") or ""
        ).strip()
        provider_user_id = str(
            payload.get("user_id") or ""
        ).strip()
        scope = str(payload.get("scope") or "").strip()

        try:
            expires_in = int(payload.get("expires_in"))
        except (TypeError, ValueError) as error:
            raise OAuthClientTemporaryError(
                "O Mercado Pago retornou uma validade de token inválida."
            ) from error

        if (
            not access_token
            or not refresh_token
            or not provider_user_id
            or expires_in <= 0
        ):
            raise OAuthClientTemporaryError(
                "O Mercado Pago não retornou todas as credenciais necessárias."
            )

        live_mode = payload.get("live_mode")

        if not isinstance(live_mode, bool):
            live_mode = None

        return OAuthTokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            provider_user_id=provider_user_id,
            expires_in=expires_in,
            scope=scope,
            live_mode=live_mode,
        )
