from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from .models import Order, OrderItem


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


def orders_for_buyer_area(*, buyer):
    """
    Retorna os pedidos da área do comprador.

    A consulta carrega antecipadamente os dados necessários para
    montar os cards sem gerar consultas adicionais para cada pedido.

    O filtro pelo comprador é obrigatório e garante o isolamento
    entre contas.
    """
    from apps.payments.models import Payment
    from apps.registrations.models import Registration

    registration_queryset = (
        Registration.objects
        .select_related("order_item")
        .order_by("position")
    )

    order_item_queryset = (
        OrderItem.objects
        .select_related(
            "ticket_type",
            "ticket_lot",
        )
        .prefetch_related(
            Prefetch(
                "registrations",
                queryset=registration_queryset,
            ),
        )
        .order_by("created_at")
    )

    payment_queryset = (
        Payment.objects
        .order_by(
            "-attempt_number",
            "-created_at",
        )
    )

    return (
        Order.objects
        .for_buyer(buyer)
        .select_related(
            "organization",
            "event",
        )
        .prefetch_related(
            Prefetch(
                "items",
                queryset=order_item_queryset,
            ),
            Prefetch(
                "payments",
                queryset=payment_queryset,
                to_attr="buyer_area_payments",
            ),
        )
        .order_by("-created_at")
    )