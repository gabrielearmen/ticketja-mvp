import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import (
    FileExtensionValidator,
    MinValueValidator,
)
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


MAX_COVER_IMAGE_SIZE = 5 * 1024 * 1024


def validate_cover_image_size(image):
    """
    Impede o envio de capas excessivamente grandes.

    O limite de 5 MB é suficiente para o MVP e reduz consumo
    desnecessário de armazenamento e memória.
    """
    if image.size > MAX_COVER_IMAGE_SIZE:
        raise ValidationError(
            "A imagem de capa deve possuir no máximo 5 MB."
        )


class SportCategory(models.TextChoices):
    RUNNING = "corrida", "Corrida"
    TRAIL_RUNNING = "trail", "Trail running"
    CYCLING = "ciclismo", "Ciclismo"
    TRIATHLON = "triatlo", "Triatlo"
    SWIMMING = "natacao", "Natação"
    WALKING = "caminhada", "Caminhada"
    OBSTACLE_RACE = "obstaculos", "Corrida de obstáculos"
    OTHER = "outro", "Outra modalidade"


class EventStatus(models.TextChoices):
    DRAFT = "rascunho", "Rascunho"
    PUBLISHED = "publicado", "Publicado"
    CANCELED = "cancelado", "Cancelado"


class BrazilianState(models.TextChoices):
    AC = "AC", "Acre"
    AL = "AL", "Alagoas"
    AP = "AP", "Amapá"
    AM = "AM", "Amazonas"
    BA = "BA", "Bahia"
    CE = "CE", "Ceará"
    DF = "DF", "Distrito Federal"
    ES = "ES", "Espírito Santo"
    GO = "GO", "Goiás"
    MA = "MA", "Maranhão"
    MT = "MT", "Mato Grosso"
    MS = "MS", "Mato Grosso do Sul"
    MG = "MG", "Minas Gerais"
    PA = "PA", "Pará"
    PB = "PB", "Paraíba"
    PR = "PR", "Paraná"
    PE = "PE", "Pernambuco"
    PI = "PI", "Piauí"
    RJ = "RJ", "Rio de Janeiro"
    RN = "RN", "Rio Grande do Norte"
    RS = "RS", "Rio Grande do Sul"
    RO = "RO", "Rondônia"
    RR = "RR", "Roraima"
    SC = "SC", "Santa Catarina"
    SP = "SP", "São Paulo"
    SE = "SE", "Sergipe"
    TO = "TO", "Tocantins"


class EventQuerySet(models.QuerySet):
    def for_organization(self, organization):
        """
        Limita eventos a uma organização específica.

        Este método será a base obrigatória das views privadas.
        """
        return self.filter(organization=organization)

    def published(self):
        return self.filter(status=EventStatus.PUBLISHED)

    def upcoming(self):
        return self.filter(event_datetime__gte=timezone.now())


class Event(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    

    organization = models.ForeignKey(
        "organizations.Organization",
        verbose_name="organização",
        on_delete=models.PROTECT,
        related_name="events",
    )

    title = models.CharField(
        verbose_name="nome do evento",
        max_length=160,
    )

    summary = models.TextField(
        verbose_name="descrição resumida",
        max_length=500,
    )

    sport_category = models.CharField(
        verbose_name="modalidade esportiva",
        max_length=20,
        choices=SportCategory.choices,
    )

    event_datetime = models.DateTimeField(
        verbose_name="data e horário do evento",
    )

    city = models.CharField(
        verbose_name="cidade",
        max_length=100,
    )

    state = models.CharField(
        verbose_name="estado",
        max_length=2,
        choices=BrazilianState.choices,
    )

    address = models.CharField(
        verbose_name="endereço",
        max_length=255,
    )

    capacity = models.PositiveIntegerField(
        verbose_name="capacidade",
    )

    status = models.CharField(
        verbose_name="situação",
        max_length=20,
        choices=EventStatus.choices,
        default=EventStatus.DRAFT,
    )

    cover_image = models.ImageField(
        verbose_name="imagem de capa",
        upload_to="events/covers/%Y/%m/",
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=(
                    "jpg",
                    "jpeg",
                    "png",
                    "webp",
                )
            ),
            validate_cover_image_size,
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

    objects = EventQuerySet.as_manager()

    class Meta:
        db_table = "events_event"
        verbose_name = "evento"
        verbose_name_plural = "eventos"
        ordering = ("event_datetime", "title")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity__gt=0),
                name="event_capacity_greater_than_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=EventStatus.values
                ),
                name="event_status_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=(
                    "organization",
                    "status",
                    "event_datetime",
                ),
                name="event_org_status_date_idx",
            ),
            models.Index(
                fields=("status", "event_datetime"),
                name="event_public_date_idx",
            ),
        ]

    def __str__(self):
        return self.title

    @property
    def is_editable(self):
        return self.status == EventStatus.DRAFT

    def clean(self):
        super().clean()

        errors = {}

        if self.capacity is not None and self.capacity <= 0:
            errors["capacity"] = (
                "A capacidade deve ser maior que zero."
            )

        if self.status == EventStatus.PUBLISHED:
            if not self.cover_image:
                errors["cover_image"] = (
                    "Adicione uma imagem de capa antes de publicar."
                )

            if (
                self.event_datetime
                and self.event_datetime <= timezone.now()
            ):
                errors["event_datetime"] = (
                    "Um evento publicado deve possuir uma data futura."
                )

        if errors:
            raise ValidationError(errors)

    def publish(self):
        """
        Executa somente a transição Rascunho -> Publicado.

        A persistência será realizada pela camada de serviços,
        dentro de uma transação no PostgreSQL.
        """
        if self.status != EventStatus.DRAFT:
            raise ValidationError(
                "Somente eventos em rascunho podem ser publicados."
            )

        original_status = self.status
        self.status = EventStatus.PUBLISHED

        try:
            self.full_clean()
        except ValidationError:
            self.status = original_status
            raise

    def cancel(self):
        """
        Executa somente a transição Publicado -> Cancelado.
        """
        if self.status != EventStatus.PUBLISHED:
            raise ValidationError(
                "Somente eventos publicados podem ser cancelados."
            )

        self.status = EventStatus.CANCELED


class TicketType(models.Model):
    """
    Categoria comercial disponível dentro de um evento.

    Exemplos:
    - Corrida 5 km
    - Corrida 10 km
    - Kit premium
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    event = models.ForeignKey(
        Event,
        verbose_name="evento",
        on_delete=models.PROTECT,
        related_name="ticket_types",
    )

    name = models.CharField(
        verbose_name="nome",
        max_length=100,
    )

    description = models.CharField(
        verbose_name="descrição",
        max_length=300,
        blank=True,
    )

    capacity = models.PositiveIntegerField(
        verbose_name="capacidade",
    )

    is_active = models.BooleanField(
        verbose_name="ativo",
        default=True,
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
        db_table = "events_ticket_type"
        verbose_name = "tipo de ingresso"
        verbose_name_plural = "tipos de ingresso"
        ordering = ("name",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity__gt=0),
                name="ticket_type_capacity_gt_zero",
            ),
            models.UniqueConstraint(
                Lower("name"),
                "event",
                name="ticket_type_name_event_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=("event", "is_active"),
                name="ticket_type_event_active_idx",
            ),
        ]

    def __str__(self):
        return f"{self.event.title} — {self.name}"

    def clean(self):
        super().clean()

        if (
            self.event_id
            and self.capacity
            and self.capacity > self.event.capacity
        ):
            raise ValidationError(
                {
                    "capacity": (
                        "A capacidade do tipo de ingresso não pode "
                        "superar a capacidade total do evento."
                    )
                }
            )


class TicketLot(models.Model):
    """
    Condição comercial de venda de um tipo de ingresso.

    A quantidade representa o limite comercial do lote. A quantidade
    efetivamente disponível será calculada com base em pedidos e
    reservas válidas.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    ticket_type = models.ForeignKey(
        TicketType,
        verbose_name="tipo de ingresso",
        on_delete=models.PROTECT,
        related_name="lots",
    )

    name = models.CharField(
        verbose_name="nome do lote",
        max_length=100,
    )

    price = models.DecimalField(
        verbose_name="preço",
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0.00")),
        ],
    )

    quantity = models.PositiveIntegerField(
        verbose_name="quantidade",
    )

    sales_start = models.DateTimeField(
        verbose_name="início das vendas",
    )

    sales_end = models.DateTimeField(
        verbose_name="encerramento das vendas",
    )

    is_active = models.BooleanField(
        verbose_name="ativo",
        default=True,
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
        db_table = "events_ticket_lot"
        verbose_name = "lote de ingresso"
        verbose_name_plural = "lotes de ingresso"
        ordering = (
            "sales_start",
            "price",
            "name",
        )
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0),
                name="ticket_lot_quantity_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name="ticket_lot_price_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    sales_start__lt=models.F("sales_end")
                ),
                name="ticket_lot_sales_period_valid",
            ),
            models.UniqueConstraint(
                Lower("name"),
                "ticket_type",
                name="ticket_lot_name_type_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=("ticket_type", "is_active"),
                name="ticket_lot_type_active_idx",
            ),
            models.Index(
                fields=("sales_start", "sales_end"),
                name="ticket_lot_sales_period_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.ticket_type.name} — "
            f"{self.name} — R$ {self.price}"
        )

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.sales_start
            and self.sales_end
            and self.sales_start >= self.sales_end
        ):
            errors["sales_end"] = (
                "O encerramento deve ser posterior ao início "
                "das vendas."
            )

        if (
            self.ticket_type_id
            and self.sales_end
            and self.sales_end
            > self.ticket_type.event.event_datetime
        ):
            errors["sales_end"] = (
                "As vendas devem terminar antes da realização "
                "do evento."
            )

        if errors:
            raise ValidationError(errors)

    @property
    def is_free(self):
        return self.price == Decimal("0.00")

    @property
    def is_in_sales_period(self):
        now = timezone.now()

        return (
            self.is_active
            and self.sales_start <= now < self.sales_end
        )


    @property
    def sales_status(self):
        if not self.is_active:
            return "inativo"

        now = timezone.now()

        if now < self.sales_start:
            return "programado"

        if now >= self.sales_end:
            return "encerrado"

        return "em-venda"

    @property
    def sales_status_label(self):
        labels = {
            "inativo": "Inativo",
            "programado": "Programado",
            "encerrado": "Encerrado",
            "em-venda": "Em venda",
        }

        return labels[self.sales_status]


