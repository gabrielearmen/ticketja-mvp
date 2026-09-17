from django.db.models import Prefetch
from django.utils import timezone

from .models import TicketLot, TicketType


def commercial_configuration_errors(event):
    """
    Retorna uma lista de impedimentos para publicação.

    A função não altera dados. Ela pode ser utilizada tanto na
    interface quanto no serviço transacional de publicação.
    """
    active_lot_queryset = (
        TicketLot.objects
        .filter(is_active=True)
        .order_by(
            "sales_start",
            "sales_end",
        )
    )

    active_ticket_types = list(
        TicketType.objects
        .filter(
            event=event,
            is_active=True,
        )
        .prefetch_related(
            Prefetch(
                "lots",
                queryset=active_lot_queryset,
                to_attr="active_lots",
            )
        )
        .order_by("name")
    )

    errors = []

    if not active_ticket_types:
        return [
            (
                "Crie pelo menos um tipo de ingresso ativo "
                "antes de publicar."
            )
        ]

    allocated_event_capacity = sum(
        ticket_type.capacity
        for ticket_type in active_ticket_types
    )

    if allocated_event_capacity > event.capacity:
        errors.append(
            (
                "A soma das capacidades dos tipos de ingresso "
                "ultrapassa a capacidade total do evento."
            )
        )

    now = timezone.now()

    for ticket_type in active_ticket_types:
        active_lots = ticket_type.active_lots

        if not active_lots:
            errors.append(
                (
                    f'O tipo "{ticket_type.name}" não possui '
                    "um lote ativo."
                )
            )
            continue

        allocated_lot_quantity = sum(
            lot.quantity
            for lot in active_lots
        )

        if allocated_lot_quantity > ticket_type.capacity:
            errors.append(
                (
                    f'A quantidade dos lotes de "{ticket_type.name}" '
                    "ultrapassa a capacidade do tipo."
                )
            )

        previous_lot = None

        for lot in active_lots:
            if lot.sales_start >= lot.sales_end:
                errors.append(
                    (
                        f'O lote "{lot.name}" possui um período '
                        "de vendas inválido."
                    )
                )

            if lot.sales_end <= now:
                errors.append(
                    (
                        f'O lote "{lot.name}" já está encerrado.'
                    )
                )

            if lot.sales_end > event.event_datetime:
                errors.append(
                    (
                        f'O lote "{lot.name}" termina depois da '
                        "realização do evento."
                    )
                )

            if (
                previous_lot is not None
                and lot.sales_start < previous_lot.sales_end
            ):
                errors.append(
                    (
                        f'Os lotes "{previous_lot.name}" e '
                        f'"{lot.name}" possuem períodos '
                        "sobrepostos."
                    )
                )

            previous_lot = lot

    return errors