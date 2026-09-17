from dataclasses import dataclass
from enum import Enum

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import (
    IntegerField,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.events.models import (
    EventStatus,
    TicketLot,
)
from apps.organizations.models import OrganizationStatus

from .models import (
    OrderItem,
    OrderStatus,
)


class TicketLotAvailabilityStatus(str, Enum):
    AVAILABLE = "disponivel"
    SOLD_OUT = "esgotado"
    SCHEDULED = "programado"
    CLOSED = "encerrado"
    INACTIVE_LOT = "lote_inativo"
    INACTIVE_TICKET_TYPE = "tipo_inativo"
    EVENT_UNAVAILABLE = "evento_indisponivel"
    ORGANIZATION_UNAVAILABLE = "organizacao_indisponivel"

    @property
    def label(self):
        labels = {
            self.AVAILABLE: "Disponível",
            self.SOLD_OUT: "Esgotado",
            self.SCHEDULED: "Vendas programadas",
            self.CLOSED: "Vendas encerradas",
            self.INACTIVE_LOT: "Lote inativo",
            self.INACTIVE_TICKET_TYPE: (
                "Tipo de ingresso inativo"
            ),
            self.EVENT_UNAVAILABLE: "Evento indisponível",
            self.ORGANIZATION_UNAVAILABLE: (
                "Organização indisponível"
            ),
        }

        return labels[self]


@dataclass(frozen=True, slots=True)
class TicketLotAvailability:
    """
    Resultado imutável do cálculo de disponibilidade.

    Esse objeto não altera o lote nem cria reservas.
    """

    ticket_lot: TicketLot
    total_quantity: int
    committed_quantity: int
    available_quantity: int
    status: TicketLotAvailabilityStatus
    reference_time: object

    @property
    def is_available(self):
        return (
            self.status
            == TicketLotAvailabilityStatus.AVAILABLE
            and self.available_quantity > 0
        )

    @property
    def status_label(self):
        return self.status.label


def _committed_quantity_for_lot(
    *,
    ticket_lot,
    reference_time,
):
    """
    Soma somente quantidades que realmente ocupam vagas.

    Ocupam vagas:
    - pedidos pagos;
    - pedidos aguardando pagamento com reserva não expirada.

    Não ocupam:
    - rascunhos;
    - reservas vencidas;
    - pedidos expirados;
    - cancelados;
    - reembolsados.
    """
    holding_inventory_filter = (
        Q(order__status=OrderStatus.PAID)
        | Q(
            order__status=OrderStatus.AWAITING_PAYMENT,
            order__reservation_expires_at__gt=reference_time,
        )
    )

    result = (
        OrderItem.objects
        .filter(ticket_lot=ticket_lot)
        .filter(holding_inventory_filter)
        .aggregate(
            total=Coalesce(
                Sum("quantity"),
                Value(0),
                output_field=IntegerField(),
            )
        )
    )

    return result["total"]


def _availability_status(
    *,
    ticket_lot,
    available_quantity,
    reference_time,
):
    ticket_type = ticket_lot.ticket_type
    event = ticket_type.event
    organization = event.organization

    if organization.status != OrganizationStatus.APPROVED:
        return (
            TicketLotAvailabilityStatus
            .ORGANIZATION_UNAVAILABLE
        )

    if (
        event.status != EventStatus.PUBLISHED
        or event.event_datetime <= reference_time
    ):
        return TicketLotAvailabilityStatus.EVENT_UNAVAILABLE

    if not ticket_type.is_active:
        return (
            TicketLotAvailabilityStatus
            .INACTIVE_TICKET_TYPE
        )

    if not ticket_lot.is_active:
        return TicketLotAvailabilityStatus.INACTIVE_LOT

    if reference_time < ticket_lot.sales_start:
        return TicketLotAvailabilityStatus.SCHEDULED

    if reference_time >= ticket_lot.sales_end:
        return TicketLotAvailabilityStatus.CLOSED

    if available_quantity <= 0:
        return TicketLotAvailabilityStatus.SOLD_OUT

    return TicketLotAvailabilityStatus.AVAILABLE


def calculate_ticket_lot_availability(
    *,
    ticket_lot,
    at=None,
):
    """
    Calcula uma fotografia da disponibilidade.

    Esta função é apropriada para exibição e consultas comuns.
    Ela não deve ser usada sozinha para confirmar uma reserva,
    porque duas requisições poderiam consultar simultaneamente.

    Para criar reservas, utilize
    lock_ticket_lot_and_calculate_availability().
    """
    reference_time = at or timezone.now()

    committed_quantity = _committed_quantity_for_lot(
        ticket_lot=ticket_lot,
        reference_time=reference_time,
    )

    available_quantity = max(
        ticket_lot.quantity - committed_quantity,
        0,
    )

    status = _availability_status(
        ticket_lot=ticket_lot,
        available_quantity=available_quantity,
        reference_time=reference_time,
    )

    return TicketLotAvailability(
        ticket_lot=ticket_lot,
        total_quantity=ticket_lot.quantity,
        committed_quantity=committed_quantity,
        available_quantity=available_quantity,
        status=status,
        reference_time=reference_time,
    )


def lock_ticket_lot_and_calculate_availability(
    *,
    ticket_lot_id,
    at=None,
):
    """
    Bloqueia o lote no PostgreSQL e recalcula a disponibilidade.

    Esta função deve obrigatoriamente ser executada dentro de
    transaction.atomic().

    Enquanto a transação estiver aberta, outra tentativa de reserva
    para o mesmo lote deverá aguardar a finalização da primeira.
    """
    database_connection = transaction.get_connection()

    if not database_connection.in_atomic_block:
        raise RuntimeError(
            "O bloqueio do lote deve ser executado dentro "
            "de transaction.atomic()."
        )

    ticket_lot = (
        TicketLot.objects
        .select_for_update()
        .select_related(
            "ticket_type",
            "ticket_type__event",
            "ticket_type__event__organization",
        )
        .get(id=ticket_lot_id)
    )

    return calculate_ticket_lot_availability(
        ticket_lot=ticket_lot,
        at=at,
    )


def validate_reservation_quantity(
    *,
    availability,
    quantity,
):
    """
    Valida uma quantidade solicitada usando o resultado calculado.

    Retorna a quantidade quando for válida.
    """
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
    ):
        raise ValidationError(
            {
                "quantity": (
                    "A quantidade deve ser um número inteiro."
                )
            }
        )

    if quantity <= 0:
        raise ValidationError(
            {
                "quantity": (
                    "A quantidade deve ser maior que zero."
                )
            }
        )

    if not availability.is_available:
        raise ValidationError(
            {
                "quantity": (
                    "Não é possível reservar este lote. "
                    f"Situação atual: "
                    f"{availability.status_label}."
                )
            }
        )

    if quantity > availability.available_quantity:
        raise ValidationError(
            {
                "quantity": (
                    "A quantidade solicitada não está disponível. "
                    f"Restam {availability.available_quantity} "
                    "vaga(s) neste lote."
                )
            }
        )

    return quantity

def calculate_ticket_lot_availabilities(
    *,
    ticket_lots,
    at=None,
):
    """
    Calcula a disponibilidade de vários lotes usando uma única
    consulta de agregação para os pedidos.

    O resultado preserva a mesma ordem recebida.
    """
    reference_time = at or timezone.now()
    ticket_lot_list = list(ticket_lots)

    if not ticket_lot_list:
        return []

    ticket_lot_ids = [
        ticket_lot.id
        for ticket_lot in ticket_lot_list
    ]

    holding_inventory_filter = (
        Q(order__status=OrderStatus.PAID)
        | Q(
            order__status=OrderStatus.AWAITING_PAYMENT,
            order__reservation_expires_at__gt=reference_time,
        )
    )

    committed_rows = (
        OrderItem.objects
        .filter(ticket_lot_id__in=ticket_lot_ids)
        .filter(holding_inventory_filter)
        .values("ticket_lot_id")
        .annotate(total=Sum("quantity"))
    )

    committed_by_lot = {
        row["ticket_lot_id"]: row["total"]
        for row in committed_rows
    }

    results = []

    for ticket_lot in ticket_lot_list:
        committed_quantity = committed_by_lot.get(
            ticket_lot.id,
            0,
        )

        available_quantity = max(
            ticket_lot.quantity - committed_quantity,
            0,
        )

        status = _availability_status(
            ticket_lot=ticket_lot,
            available_quantity=available_quantity,
            reference_time=reference_time,
        )

        results.append(
            TicketLotAvailability(
                ticket_lot=ticket_lot,
                total_quantity=ticket_lot.quantity,
                committed_quantity=committed_quantity,
                available_quantity=available_quantity,
                status=status,
                reference_time=reference_time,
            )
        )

    return results