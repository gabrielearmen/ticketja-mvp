from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, register
from django.core.exceptions import ImproperlyConfigured

from .crypto import validate_encryption_configuration


@register(Tags.security)
def marketplace_configuration_check(app_configs, **kwargs):
    del app_configs, kwargs

    if not (
        settings.MARKETPLACE_PAYMENTS_ENABLED
        or settings.MARKETPLACE_OAUTH_ENABLED
    ):
        return []

    errors = []

    required_values = {
        "MERCADO_PAGO_CLIENT_ID": settings.MERCADO_PAGO_CLIENT_ID,
        "MERCADO_PAGO_CLIENT_SECRET": (
            settings.MERCADO_PAGO_CLIENT_SECRET
        ),
        "MERCADO_PAGO_OAUTH_REDIRECT_URI": (
            settings.MERCADO_PAGO_OAUTH_REDIRECT_URI
        ),
    }

    for name, value in required_values.items():
        if not value:
            errors.append(
                Error(
                    f"{name} não foi configurada.",
                    id="marketplace.E001",
                )
            )

    redirect_uri = settings.MERCADO_PAGO_OAUTH_REDIRECT_URI

    if redirect_uri:
        parsed_uri = urlparse(redirect_uri)
        is_localhost = parsed_uri.hostname in {
            "localhost",
            "127.0.0.1",
        }

        if parsed_uri.scheme != "https" and not is_localhost:
            errors.append(
                Error(
                    "MERCADO_PAGO_OAUTH_REDIRECT_URI deve usar HTTPS.",
                    id="marketplace.E002",
                )
            )

    try:
        validate_encryption_configuration()
    except ImproperlyConfigured as error:
        errors.append(
            Error(str(error), id="marketplace.E003")
        )

    if settings.MARKETPLACE_PAYMENTS_ENABLED:
        if not settings.MARKETPLACE_OAUTH_ENABLED:
            errors.append(
                Error(
                    "MARKETPLACE_OAUTH_ENABLED deve estar ativa para cobranças marketplace.",
                    id="marketplace.E004",
                )
            )

        if not settings.MERCADO_PAGO_WEBHOOK_SECRET:
            errors.append(
                Error(
                    "MERCADO_PAGO_WEBHOOK_SECRET não foi configurada.",
                    id="marketplace.E005",
                )
            )

        parsed_api = urlparse(settings.MERCADO_PAGO_API_BASE_URL)

        if parsed_api.scheme != "https" or not parsed_api.netloc:
            errors.append(
                Error(
                    "MERCADO_PAGO_API_BASE_URL deve usar HTTPS.",
                    id="marketplace.E006",
                )
            )

    return errors
