from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .base import PaymentGateway
from .base import (
    PaymentGatewayConfigurationError,
    PaymentGatewayTemporaryError,
)


@lru_cache(maxsize=1)
def get_payment_gateway():
    """
    Cria o gateway definido nas configurações do Django.

    O cache evita recriar o cliente a cada chamada.
    """
    gateway_path = getattr(
        settings,
        "PAYMENT_GATEWAY_CLASS",
        "",
    ).strip()

    if not gateway_path:
        raise ImproperlyConfigured(
            "PAYMENT_GATEWAY_CLASS não foi configurada."
        )

    gateway_class = import_string(gateway_path)
    gateway = gateway_class()

    if not isinstance(gateway, PaymentGateway):
        raise ImproperlyConfigured(
            "PAYMENT_GATEWAY_CLASS deve implementar "
            "PaymentGateway."
        )

    return gateway


def clear_payment_gateway_cache():
    """
    Utilizado principalmente em testes que alteram configurações.
    """
    get_payment_gateway.cache_clear()


def get_payment_gateway_for_organization(organization):
    """Seleciona a credencial do recebedor quando o marketplace está ativo."""
    if not settings.MARKETPLACE_PAYMENTS_ENABLED:
        return get_payment_gateway()

    from apps.marketplace.oauth_client import (
        OAuthClientRejectedError,
        OAuthClientTemporaryError,
    )
    from apps.marketplace.tokens import (
        PaymentAccountUnavailable,
        payment_credentials_for_organization,
    )

    from .mercado_pago import MercadoPagoGateway

    try:
        credentials = payment_credentials_for_organization(
            organization=organization
        )
    except OAuthClientTemporaryError as error:
        raise PaymentGatewayTemporaryError(
            "Não foi possível renovar a autorização do recebedor."
        ) from error
    except (PaymentAccountUnavailable, OAuthClientRejectedError) as error:
        raise PaymentGatewayConfigurationError(
            "A conta Mercado Pago do organizador precisa ser conectada novamente."
        ) from error

    expected_live_mode = not settings.MERCADO_PAGO_TEST_MODE

    if (
        credentials.is_live_mode is not None
        and credentials.is_live_mode != expected_live_mode
    ):
        raise PaymentGatewayConfigurationError(
            "A conta recebedora pertence a um ambiente diferente da aplicação."
        )

    return MercadoPagoGateway(
        access_token=credentials.access_token
    )


def get_payment_gateway_for_payment(payment):
    is_legacy_order = (
        bool(payment.provider_order_id)
        and bool(payment.provider_payment_id)
        and payment.provider_order_id
        != payment.provider_payment_id
    )

    if is_legacy_order:
        from .mercado_pago import MercadoPagoGateway

        return MercadoPagoGateway(
            access_token=settings.MERCADO_PAGO_ACCESS_TOKEN,
            use_orders_api=True,
        )

    order = payment.order

    if not hasattr(order, "organization"):
        from apps.orders.models import Order

        order = Order.objects.select_related("organization").get(
            id=payment.order_id
        )

    return get_payment_gateway_for_organization(
        order.organization
    )
