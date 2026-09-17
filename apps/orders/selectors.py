from django.shortcuts import get_object_or_404

from .models import Order


def order_for_buyer_or_404(
    *,
    buyer,
    public_code,
):
    """
    Retorna um pedido exclusivamente para seu comprador.

    Alterar o código público na URL não concede acesso ao pedido
    de outra pessoa.
    """
    return get_object_or_404(
        Order.objects
        .for_buyer(buyer)
        .select_related(
            "buyer",
            "organization",
            "event",
        )
        .prefetch_related(
            "items",
            "items__ticket_type",
            "items__ticket_lot",
        ),
        public_code=public_code,
    )