import uuid

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
)

from apps.events.selectors import (
    public_event_for_detail_or_404,
)

from .availability import (
    calculate_ticket_lot_availabilities,
)
from .forms import StartCheckoutForm
from .selectors import order_for_buyer_or_404
from .services import (
    create_reservation_order,
    expire_order_reservation,
)


def _add_service_errors_to_form(form, error):
    """
    Converte erros da camada de serviços em erros de formulário.
    """
    field_mapping = {
        "ticket_lot_id": "ticket_lot",
        "quantity": "quantity",
        "idempotency_key": "idempotency_key",
    }

    if hasattr(error, "message_dict"):
        for service_field, error_messages in (
            error.message_dict.items()
        ):
            form_field = field_mapping.get(service_field)

            if form_field not in form.fields:
                form_field = None

            for error_message in error_messages:
                form.add_error(
                    form_field,
                    error_message,
                )

        return

    for error_message in error.messages:
        form.add_error(None, error_message)


def _checkout_offers(form):
    """
    Organiza os lotes e suas disponibilidades para o template.
    """
    ticket_lots = list(
        form.fields["ticket_lot"].queryset
    )

    return calculate_ticket_lot_availabilities(
        ticket_lots=ticket_lots,
    )


@login_required
@require_http_methods(["GET", "POST"])
def start_checkout(request, event_id):
    """
    Apresenta a seleção e cria a reserva no envio válido.
    """
    event = public_event_for_detail_or_404(
        event_id=event_id,
    )

    if request.method == "POST":
        form = StartCheckoutForm(
            request.POST,
            event=event,
        )

        if form.is_valid():
            ticket_lot = form.cleaned_data["ticket_lot"]

            try:
                result = create_reservation_order(
                    buyer=request.user,
                    ticket_lot_id=ticket_lot.id,
                    quantity=form.cleaned_data["quantity"],
                    idempotency_key=(
                        form.cleaned_data["idempotency_key"]
                    ),
                )
            except ValidationError as error:
                _add_service_errors_to_form(
                    form,
                    error,
                )
            else:
                return redirect(
                    "orders:checkout-detail",
                    public_code=result.order.public_code,
                )
    else:
        form = StartCheckoutForm(
            event=event,
            initial={
                "idempotency_key": uuid.uuid4(),
                "quantity": 1,
            },
        )

    offers = _checkout_offers(form)

    context = {
        "event": event,
        "form": form,
        "offers": offers,
        "has_available_offer": any(
            offer.is_available
            for offer in offers
        ),
    }

    return render(
        request,
        "orders/checkout_start.html",
        context,
    )


@login_required
@require_GET
def checkout_detail(request, public_code):
    """
    Mostra o resumo de uma reserva pertencente ao comprador.
    """
    order = order_for_buyer_or_404(
        buyer=request.user,
        public_code=public_code,
    )

    if order.is_expirable:
        expiration_result = expire_order_reservation(
            order_id=order.id,
        )
        order = expiration_result.order

    context = {
        "order": order,
        "order_items": order.items.all(),
    }

    return render(
        request,
        "orders/checkout_detail.html",
        context,
    )