from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .crypto import SecretDecryptionError, decrypt_secret, encrypt_secret
from .models import OrganizationPaymentAccount, PaymentAccountStatus
from .oauth_client import (
    MercadoPagoOAuthClient,
    OAuthClientRejectedError,
)


TOKEN_REFRESH_MARGIN = timedelta(minutes=10)


class PaymentAccountUnavailable(Exception):
    """A organização não possui credenciais utilizáveis."""


@dataclass(frozen=True, slots=True)
class OrganizationPaymentCredentials:
    access_token: str
    provider_user_id: str
    is_live_mode: bool | None


def _credentials_from(account):
    try:
        access_token = decrypt_secret(
            account.access_token_ciphertext
        )
    except SecretDecryptionError as error:
        raise PaymentAccountUnavailable(
            "A credencial da conta recebedora não pôde ser recuperada."
        ) from error

    return OrganizationPaymentCredentials(
        access_token=access_token,
        provider_user_id=account.provider_user_id,
        is_live_mode=account.is_live_mode,
    )


def payment_credentials_for_organization(
    *,
    organization,
    client=None,
    at=None,
):
    reference_time = at or timezone.now()
    account = OrganizationPaymentAccount.objects.filter(
        organization=organization,
        status=PaymentAccountStatus.ACTIVE,
    ).first()

    if account is None or not account.is_usable:
        raise PaymentAccountUnavailable(
            "A organização ainda não conectou uma conta Mercado Pago."
        )

    token_is_current = (
        account.access_token_expires_at is not None
        and account.access_token_expires_at
        > reference_time + TOKEN_REFRESH_MARGIN
    )

    if token_is_current:
        return _credentials_from(account)

    try:
        refresh_token = decrypt_secret(
            account.refresh_token_ciphertext
        )
    except SecretDecryptionError as error:
        raise PaymentAccountUnavailable(
            "A conta Mercado Pago precisa ser conectada novamente."
        ) from error

    selected_client = client or MercadoPagoOAuthClient()

    try:
        token = selected_client.refresh_access_token(
            refresh_token=refresh_token
        )
    except OAuthClientRejectedError:
        OrganizationPaymentAccount.objects.filter(
            id=account.id,
            status=PaymentAccountStatus.ACTIVE,
        ).update(
            status=PaymentAccountStatus.REAUTH_REQUIRED,
            last_error_code="refresh_rejected",
            updated_at=reference_time,
        )
        raise

    with transaction.atomic():
        locked_account = (
            OrganizationPaymentAccount.objects
            .select_for_update()
            .get(id=account.id)
        )

        another_request_refreshed = (
            locked_account.access_token_expires_at is not None
            and locked_account.access_token_expires_at
            > reference_time + TOKEN_REFRESH_MARGIN
            and locked_account.last_refreshed_at
            != account.last_refreshed_at
        )

        if another_request_refreshed:
            return _credentials_from(locked_account)

        if token.provider_user_id != locked_account.provider_user_id:
            locked_account.status = PaymentAccountStatus.REAUTH_REQUIRED
            locked_account.last_error_code = "receiver_changed"
            locked_account.save(
                update_fields=(
                    "status",
                    "last_error_code",
                    "updated_at",
                )
            )
            raise PaymentAccountUnavailable(
                "O recebedor retornado pelo Mercado Pago foi alterado."
            )

        locked_account.access_token_ciphertext = encrypt_secret(
            token.access_token
        )
        locked_account.refresh_token_ciphertext = encrypt_secret(
            token.refresh_token
        )
        locked_account.access_token_expires_at = (
            reference_time + timedelta(seconds=token.expires_in)
        )
        locked_account.granted_scopes = token.scope
        locked_account.is_live_mode = token.live_mode
        locked_account.last_refreshed_at = reference_time
        locked_account.last_error_code = ""
        locked_account.save(
            update_fields=(
                "access_token_ciphertext",
                "refresh_token_ciphertext",
                "access_token_expires_at",
                "granted_scopes",
                "is_live_mode",
                "last_refreshed_at",
                "last_error_code",
                "updated_at",
            )
        )

        return _credentials_from(locked_account)
