import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.organizations.models import (
    MembershipRole,
    OrganizationMembership,
    OrganizationStatus,
)

from .crypto import decrypt_secret, encrypt_secret
from .models import (
    MarketplaceProvider,
    OAuthAuthorizationAttempt,
    OrganizationPaymentAccount,
    PaymentAccountStatus,
)
from .oauth_client import MercadoPagoOAuthClient


class MarketplaceConnectionError(Exception):
    """Falha segura no fluxo de conexão da conta recebedora."""


class OAuthStateError(MarketplaceConnectionError):
    """O state OAuth é inválido, expirou ou já foi utilizado."""


@dataclass(frozen=True, slots=True)
class AuthorizationStart:
    authorization_url: str
    expires_at: object


@dataclass(frozen=True, slots=True)
class ConnectionResult:
    account: OrganizationPaymentAccount


def _assert_financial_owner(*, organization, user):
    membership_exists = OrganizationMembership.objects.filter(
        organization=organization,
        organization__status=OrganizationStatus.APPROVED,
        user=user,
        role=MembershipRole.OWNER,
        is_active=True,
    ).exists()

    if not membership_exists:
        raise PermissionDenied(
            "Somente o proprietário pode administrar a conta de recebimento."
        )


def _validate_oauth_settings():
    if not settings.MARKETPLACE_OAUTH_ENABLED:
        raise ImproperlyConfigured(
            "A conexão OAuth do marketplace ainda não foi habilitada."
        )

    required_values = (
        settings.MERCADO_PAGO_CLIENT_ID,
        settings.MERCADO_PAGO_CLIENT_SECRET,
        settings.MERCADO_PAGO_OAUTH_REDIRECT_URI,
    )

    if not all(required_values):
        raise ImproperlyConfigured(
            "As credenciais OAuth do Mercado Pago estão incompletas."
        )

    parsed_redirect = urlparse(
        settings.MERCADO_PAGO_OAUTH_REDIRECT_URI
    )
    is_localhost = parsed_redirect.hostname in {
        "localhost",
        "127.0.0.1",
    }

    if parsed_redirect.scheme != "https" and not is_localhost:
        raise ImproperlyConfigured(
            "O retorno OAuth deve usar HTTPS."
        )


def _state_digest(raw_state):
    return hashlib.sha256(
        str(raw_state).encode("utf-8")
    ).hexdigest()


def _code_challenge(code_verifier):
    digest = hashlib.sha256(
        code_verifier.encode("ascii")
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@transaction.atomic
def begin_mercado_pago_connection(
    *,
    organization,
    user,
    at=None,
):
    _assert_financial_owner(
        organization=organization,
        user=user,
    )
    _validate_oauth_settings()

    reference_time = at or timezone.now()
    raw_state = secrets.token_urlsafe(48)
    code_verifier = secrets.token_urlsafe(64)
    expires_at = reference_time + timedelta(
        minutes=settings.MARKETPLACE_OAUTH_STATE_TTL_MINUTES
    )

    OAuthAuthorizationAttempt.objects.create(
        organization=organization,
        initiated_by=user,
        state_digest=_state_digest(raw_state),
        code_verifier_ciphertext=encrypt_secret(code_verifier),
        redirect_uri=settings.MERCADO_PAGO_OAUTH_REDIRECT_URI,
        expires_at=expires_at,
    )

    query = urlencode(
        {
            "client_id": settings.MERCADO_PAGO_CLIENT_ID,
            "response_type": "code",
            "platform_id": "mp",
            "state": raw_state,
            "redirect_uri": settings.MERCADO_PAGO_OAUTH_REDIRECT_URI,
            "code_challenge": _code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
    )

    authorization_url = (
        f"{settings.MERCADO_PAGO_OAUTH_AUTHORIZE_URL}?{query}"
    )

    return AuthorizationStart(
        authorization_url=authorization_url,
        expires_at=expires_at,
    )


def _consume_authorization_attempt(*, state, user, at):
    digest = _state_digest(state)

    with transaction.atomic():
        attempt = (
            OAuthAuthorizationAttempt.objects
            .select_for_update()
            .select_related("organization")
            .filter(state_digest=digest)
            .first()
        )

        if (
            attempt is None
            or attempt.initiated_by_id != user.id
            or attempt.consumed_at is not None
            or attempt.expires_at <= at
        ):
            raise OAuthStateError(
                "A autorização expirou ou já foi utilizada. Inicie novamente."
            )

        _assert_financial_owner(
            organization=attempt.organization,
            user=user,
        )

        attempt.consumed_at = at
        attempt.save(update_fields=("consumed_at",))

        return (
            attempt.organization,
            attempt.redirect_uri,
            decrypt_secret(attempt.code_verifier_ciphertext),
        )


def complete_mercado_pago_connection(
    *,
    state,
    code,
    user,
    client=None,
    at=None,
):
    _validate_oauth_settings()
    reference_time = at or timezone.now()
    normalized_state = str(state or "").strip()
    normalized_code = str(code or "").strip()

    if not normalized_state or not normalized_code:
        raise OAuthStateError(
            "O retorno do Mercado Pago está incompleto."
        )

    organization, redirect_uri, code_verifier = (
        _consume_authorization_attempt(
            state=normalized_state,
            user=user,
            at=reference_time,
        )
    )

    selected_client = client or MercadoPagoOAuthClient()
    token = selected_client.exchange_authorization_code(
        code=normalized_code,
        state=normalized_state,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )

    try:
        with transaction.atomic():
            account = (
                OrganizationPaymentAccount.objects
                .select_for_update()
                .filter(organization=organization)
                .first()
            )

            if account is None:
                account = OrganizationPaymentAccount(
                    organization=organization,
                )

            account_in_use = (
                OrganizationPaymentAccount.objects.filter(
                    provider=MarketplaceProvider.MERCADO_PAGO,
                    provider_user_id=token.provider_user_id,
                )
                .exclude(organization=organization)
                .exists()
            )

            if account_in_use:
                raise MarketplaceConnectionError(
                    "Esta conta Mercado Pago já está vinculada a outra organização."
                )

            account.provider = MarketplaceProvider.MERCADO_PAGO
            account.status = PaymentAccountStatus.ACTIVE
            account.provider_user_id = token.provider_user_id
            account.is_live_mode = token.live_mode
            account.access_token_ciphertext = encrypt_secret(
                token.access_token
            )
            account.refresh_token_ciphertext = encrypt_secret(
                token.refresh_token
            )
            account.access_token_expires_at = (
                reference_time + timedelta(seconds=token.expires_in)
            )
            account.granted_scopes = token.scope
            account.connected_at = reference_time
            account.last_refreshed_at = reference_time
            account.revoked_at = None
            account.last_error_code = ""
            account.full_clean()
            account.save()
    except IntegrityError as error:
        raise MarketplaceConnectionError(
            "Não foi possível vincular esta conta Mercado Pago."
        ) from error

    return ConnectionResult(account=account)
