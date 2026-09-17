import secrets
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


MONEY_ZERO = Decimal("0.00")

ORDER_PUBLIC_CODE_ALPHABET = (
    "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
)


def generate_order_public_code():
    """
    Gera um código público não sequencial.

    Caracteres visualmente ambíguos, como I, O, 0 e 1,
    não fazem parte do alfabeto.
    """
    random_part = "".join(
        secrets.choice(ORDER_PUBLIC_CODE_ALPHABET)
        for _ in range(12)
    )

    return f"TJ-{random_part}"


class OrderStatus(models.TextChoices):
    DRAFT = "rascunho", "Rascunho"
    AWAITING_PAYMENT = (
        "aguardando_pagamento",
        "Aguardando pagamento",
    )
    PAID = "pago", "Pago"
    EXPIRED = "expirado", "Expirado"
    CANCELED = "cancelado", "Cancelado"
    REFUNDED = "reembolsado", "Reembolsado"


class OrderQuerySet(models.QuerySet):
    def for_buyer(self, buyer):
        """
        Limita pedidos ao comprador informado.
        """
        return self.filter(buyer=buyer)

    def for_organization(self, organization):
        """
        Limita pedidos à organização informada.
        """
        return self.filter(organization=organization)

    def awaiting_payment(self):
        return self.filter(
            status=OrderStatus.AWAITING_PAYMENT,
        )

    def expired_reservations(self, *, at=None):
        """
        Localiza reservas que ultrapassaram o prazo.
        """
        reference_time = at or timezone.now()

        return self.filter(
            status=OrderStatus.AWAITING_PAYMENT,
            reservation_expires_at__lte=reference_time,
        )

    def holding_inventory(self, *, at=None):
        """
        Retorna pedidos que atualmente ocupam vagas.

        Ocupam vagas:
        - pedidos pagos;
        - pedidos aguardando pagamento e ainda não expirados.
        """
        reference_time = at or timezone.now()

        return self.filter(
            models.Q(status=OrderStatus.PAID)
            | models.Q(
                status=OrderStatus.AWAITING_PAYMENT,
                reservation_expires_at__gt=reference_time,
            )
        )


class Order(models.Model):
    """
    Representa uma compra ou tentativa de compra.

    Os valores monetários são congelados no pedido para preservar
    o histórico, mesmo que as condições comerciais sejam alteradas
    futuramente.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    public_code = models.CharField(
        verbose_name="código público",
        max_length=20,
        unique=True,
        editable=False,
        default=generate_order_public_code,
    )

    idempotency_key = models.UUIDField(
        verbose_name="chave de idempotência",
        unique=True,
        editable=False,
        default=uuid.uuid4,
    )

    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="comprador",
        on_delete=models.PROTECT,
        related_name="orders",
    )

    organization = models.ForeignKey(
        "organizations.Organization",
        verbose_name="organização",
        on_delete=models.PROTECT,
        related_name="orders",
    )

    event = models.ForeignKey(
        "events.Event",
        verbose_name="evento",
        on_delete=models.PROTECT,
        related_name="orders",
    )

    status = models.CharField(
        verbose_name="situação",
        max_length=30,
        choices=OrderStatus.choices,
        default=OrderStatus.DRAFT,
    )

    subtotal = models.DecimalField(
        verbose_name="subtotal",
        max_digits=14,
        decimal_places=2,
        default=MONEY_ZERO,
        validators=[
            MinValueValidator(MONEY_ZERO),
        ],
    )

    service_fee = models.DecimalField(
        verbose_name="taxa de serviço",
        max_digits=14,
        decimal_places=2,
        default=MONEY_ZERO,
        validators=[
            MinValueValidator(MONEY_ZERO),
        ],
    )

    total = models.DecimalField(
        verbose_name="total",
        max_digits=14,
        decimal_places=2,
        default=MONEY_ZERO,
        validators=[
            MinValueValidator(MONEY_ZERO),
        ],
    )

    reservation_expires_at = models.DateTimeField(
        verbose_name="expiração da reserva",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        verbose_name="criado em",
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        verbose_name="atualizado em",
        auto_now=True,
    )

    objects = OrderQuerySet.as_manager()

    class Meta:
        db_table = "orders_order"
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0),
                name="ord_subtotal_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(service_fee__gte=0),
                name="ord_fee_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(total__gte=0),
                name="ord_total_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    total=(
                        models.F("subtotal")
                        + models.F("service_fee")
                    )
                ),
                name="ord_total_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=OrderStatus.values,
                ),
                name="ord_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(
                        status=OrderStatus.AWAITING_PAYMENT,
                    )
                    | models.Q(
                        reservation_expires_at__isnull=False,
                    )
                ),
                name="ord_waiting_expiry_required",
            ),
        ]
        indexes = [
            models.Index(
                fields=(
                    "organization",
                    "status",
                    "created_at",
                ),
                name="ord_org_status_created_idx",
            ),
            models.Index(
                fields=(
                    "buyer",
                    "status",
                    "created_at",
                ),
                name="ord_buyer_status_created_idx",
            ),
            models.Index(
                fields=(
                    "event",
                    "status",
                    "created_at",
                ),
                name="ord_event_status_created_idx",
            ),
            models.Index(
                fields=(
                    "status",
                    "reservation_expires_at",
                ),
                name="ord_status_expiry_idx",
            ),
        ]

    def __str__(self):
        return f"Pedido {self.public_code}"

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.event_id
            and self.organization_id
            and self.event.organization_id
            != self.organization_id
        ):
            errors["organization"] = (
                "A organização do pedido deve ser a mesma "
                "organização responsável pelo evento."
            )

        expected_total = (
            (self.subtotal or MONEY_ZERO)
            + (self.service_fee or MONEY_ZERO)
        )

        if self.total is not None and self.total != expected_total:
            errors["total"] = (
                "O total deve ser igual ao subtotal somado "
                "à taxa de serviço."
            )

        if (
            self.status == OrderStatus.AWAITING_PAYMENT
            and self.reservation_expires_at is None
        ):
            errors["reservation_expires_at"] = (
                "Um pedido aguardando pagamento deve possuir "
                "uma data de expiração da reserva."
            )

        if errors:
            raise ValidationError(errors)

    @property
    def is_reservation_active(self):
        """
        Indica se a reserva temporária ainda está válida.
        """
        return (
            self.status == OrderStatus.AWAITING_PAYMENT
            and self.reservation_expires_at is not None
            and self.reservation_expires_at > timezone.now()
        )

    @property
    def is_expirable(self):
        """
        Indica se o pedido deve ser marcado como expirado.
        """
        return (
            self.status == OrderStatus.AWAITING_PAYMENT
            and self.reservation_expires_at is not None
            and self.reservation_expires_at <= timezone.now()
        )

    @property
    def holds_inventory(self):
        """
        Informa se o pedido ocupa vagas neste momento.
        """
        return (
            self.status == OrderStatus.PAID
            or self.is_reservation_active
        )


class OrderItem(models.Model):
    """
    Representa uma linha do pedido.

    A quantidade e o preço unitário são congelados quando a reserva
    é criada. Alterações futuras no lote não modificam este registro.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    order = models.ForeignKey(
        Order,
        verbose_name="pedido",
        on_delete=models.PROTECT,
        related_name="items",
    )

    ticket_type = models.ForeignKey(
        "events.TicketType",
        verbose_name="tipo de ingresso",
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    ticket_lot = models.ForeignKey(
        "events.TicketLot",
        verbose_name="lote",
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    quantity = models.PositiveIntegerField(
        verbose_name="quantidade",
    )

    unit_price = models.DecimalField(
        verbose_name="preço unitário",
        max_digits=14,
        decimal_places=2,
        validators=[
            MinValueValidator(MONEY_ZERO),
        ],
    )

    subtotal = models.DecimalField(
        verbose_name="subtotal",
        max_digits=14,
        decimal_places=2,
        validators=[
            MinValueValidator(MONEY_ZERO),
        ],
    )

    created_at = models.DateTimeField(
        verbose_name="criado em",
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        verbose_name="atualizado em",
        auto_now=True,
    )

    class Meta:
        db_table = "orders_order_item"
        verbose_name = "item do pedido"
        verbose_name_plural = "itens do pedido"
        ordering = ("created_at",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="ord_item_qty_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="ord_item_price_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(subtotal__gte=0),
                name="ord_item_subtotal_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    subtotal=(
                        models.F("unit_price")
                        * models.F("quantity")
                    )
                ),
                name="ord_item_subtotal_consistent",
            ),
            models.UniqueConstraint(
                fields=("order", "ticket_lot"),
                name="ord_item_order_lot_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=("ticket_lot", "order"),
                name="ord_item_lot_order_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.order.public_code} — "
            f"{self.ticket_type.name} × {self.quantity}"
        )

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.ticket_lot_id
            and self.ticket_type_id
            and self.ticket_lot.ticket_type_id
            != self.ticket_type_id
        ):
            errors["ticket_lot"] = (
                "O lote selecionado não pertence ao tipo "
                "de ingresso informado."
            )

        if (
            self.order_id
            and self.ticket_type_id
            and self.ticket_type.event_id
            != self.order.event_id
        ):
            errors["ticket_type"] = (
                "O tipo de ingresso não pertence ao evento "
                "deste pedido."
            )

        if self.quantity is not None and self.quantity <= 0:
            errors["quantity"] = (
                "A quantidade deve ser maior que zero."
            )

        if (
            self.unit_price is not None
            and self.quantity is not None
        ):
            expected_subtotal = (
                self.unit_price * self.quantity
            )

            if self.subtotal != expected_subtotal:
                errors["subtotal"] = (
                    "O subtotal do item deve ser igual ao "
                    "preço unitário multiplicado pela quantidade."
                )

        if errors:
            raise ValidationError(errors)

    @property
    def calculated_subtotal(self):
        return self.unit_price * self.quantity