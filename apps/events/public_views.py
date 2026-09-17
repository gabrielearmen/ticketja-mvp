from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .selectors import public_event_for_detail_or_404


@require_GET
def public_event_detail(request, event_id):
    """
    Apresenta os dados públicos e a oferta comercial de um evento.

    Esta view não cria pedidos nem modifica o banco de dados.
    Ela apenas organiza os dados que serão apresentados na interface.
    """
    event = public_event_for_detail_or_404(
        event_id=event_id,
    )

    now = timezone.now()
    ticket_offers = []

    for ticket_type in event.public_ticket_types:
        lots = list(ticket_type.public_lots)

        current_lot = next(
            (
                lot
                for lot in lots
                if lot.sales_start <= now < lot.sales_end
            ),
            None,
        )

        next_lot = next(
            (
                lot
                for lot in lots
                if lot.sales_start > now
            ),
            None,
        )

        closed_lot = next(
            (
                lot
                for lot in reversed(lots)
                if lot.sales_end <= now
            ),
            None,
        )

        if current_lot:
            displayed_lot = current_lot
            sales_state = "open"
            sales_state_label = "Em venda"
        elif next_lot:
            displayed_lot = next_lot
            sales_state = "scheduled"
            sales_state_label = "Vendas programadas"
        elif closed_lot:
            displayed_lot = closed_lot
            sales_state = "closed"
            sales_state_label = "Vendas encerradas"
        else:
            displayed_lot = None
            sales_state = "unavailable"
            sales_state_label = "Indisponível"

        ticket_offers.append(
            {
                "ticket_type": ticket_type,
                "lot": displayed_lot,
                "sales_state": sales_state,
                "sales_state_label": sales_state_label,
                "is_on_sale": sales_state == "open",
            }
        )

    context = {
        "event": event,
        "ticket_offers": ticket_offers,
        "has_open_sales": any(
            offer["is_on_sale"]
            for offer in ticket_offers
        ),
    }

    return render(
        request,
        "events/public/event_detail.html",
        context,
    )