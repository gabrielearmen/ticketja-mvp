from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .base import PaymentGateway


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