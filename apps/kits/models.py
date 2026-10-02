import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower


class EventKit(models.Model):
    """
    Kit configurado para um evento.

    Um mesmo kit pode ser vinculado a vários tipos de ingresso.
    A seleção individual de tamanho será adicionada à inscrição
    em uma fase posterior.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    event = models.ForeignKey(
        "events.Event",
        verbose_name="evento",
        on_delete=models.PROTECT,
        related_name="kits",
    )

    name = models.CharField(
        verbose_name="nome do kit",
        max_length=120,
    )

    description = models.TextField(
        verbose_name="conteúdo do kit",
        max_length=500,
        blank=True,
    )

    is_required = models.BooleanField(
        verbose_name="escolha obrigatória",
        default=True,
    )

    is_active = models.BooleanField(
        verbose_name="kit ativo",
        default=True,
    )

    ticket_types = models.ManyToManyField(
        "events.TicketType",
        verbose_name="tipos de ingresso",
        through="TicketTypeKit",
        through_fields=(
            "kit",
            "ticket_type",
        ),
        related_name="event_kits",
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

    class Meta:
        db_table = "kits_event_kit"
        verbose_name = "kit do evento"
        verbose_name_plural = "kits dos eventos"
        ordering = (
            "event",
            "name",
        )
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "event",
                name="kits_event_name_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=(
                    "event",
                    "is_active",
                ),
                name="kits_event_active_idx",
            ),
        ]

    def __str__(self):
        return f"{self.event.title} — {self.name}"


class KitOption(models.Model):
    """
    Variação com estoque próprio.

    Exemplos:
    - P
    - M
    - G
    - GG
    - Sem tamanho
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    kit = models.ForeignKey(
        EventKit,
        verbose_name="kit",
        on_delete=models.PROTECT,
        related_name="options",
    )

    name = models.CharField(
        verbose_name="opção ou tamanho",
        max_length=60,
    )

    stock_quantity = models.PositiveIntegerField(
        verbose_name="estoque total",
    )

    is_active = models.BooleanField(
        verbose_name="opção ativa",
        default=True,
    )

    created_at = models.DateTimeField(
        verbose_name="criada em",
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        verbose_name="atualizada em",
        auto_now=True,
    )

    class Meta:
        db_table = "kits_kit_option"
        verbose_name = "opção de kit"
        verbose_name_plural = "opções de kit"
        ordering = (
            "kit",
            "name",
        )
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    stock_quantity__gt=0,
                ),
                name="kits_option_stock_gt_zero",
            ),
            models.UniqueConstraint(
                Lower("name"),
                "kit",
                name="kits_option_name_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=(
                    "kit",
                    "is_active",
                ),
                name="kits_option_active_idx",
            ),
        ]

    def __str__(self):
        return f"{self.kit.name} — {self.name}"

    def clean(self):
        super().clean()

        if (
            self.stock_quantity is not None
            and self.stock_quantity <= 0
        ):
            raise ValidationError(
                {
                    "stock_quantity": (
                        "O estoque total deve ser maior "
                        "que zero."
                    )
                }
            )


class TicketTypeKit(models.Model):
    """
    Vincula um kit a um tipo de ingresso.

    A validação impede vincular objetos pertencentes a eventos
    diferentes.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    kit = models.ForeignKey(
        EventKit,
        verbose_name="kit",
        on_delete=models.PROTECT,
        related_name="ticket_type_assignments",
    )

    ticket_type = models.ForeignKey(
        "events.TicketType",
        verbose_name="tipo de ingresso",
        on_delete=models.PROTECT,
        related_name="kit_assignments",
    )

    created_at = models.DateTimeField(
        verbose_name="criado em",
        auto_now_add=True,
    )

    class Meta:
        db_table = "kits_ticket_type_kit"
        verbose_name = "vínculo de kit e ingresso"
        verbose_name_plural = "vínculos de kits e ingressos"
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "kit",
                    "ticket_type",
                ),
                name="kits_type_kit_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=(
                    "ticket_type",
                    "kit",
                ),
                name="kits_type_kit_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.ticket_type.name} — "
            f"{self.kit.name}"
        )

    def clean(self):
        super().clean()

        if (
            self.kit_id
            and self.ticket_type_id
            and self.kit.event_id
            != self.ticket_type.event_id
        ):
            raise ValidationError(
                {
                    "ticket_type": (
                        "O tipo de ingresso e o kit devem "
                        "pertencer ao mesmo evento."
                    )
                }
            )

class RegistrationKitSelection(models.Model):
    """
    Escolha individual de uma opção de kit.

    Cada inscrição pode possuir uma escolha para cada kit
    aplicável ao seu tipo de ingresso.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    registration = models.ForeignKey(
        "registrations.Registration",
        verbose_name="inscrição",
        on_delete=models.PROTECT,
        related_name="kit_selections",
    )

    kit = models.ForeignKey(
        EventKit,
        verbose_name="kit",
        on_delete=models.PROTECT,
        related_name="registration_selections",
    )

    option = models.ForeignKey(
        KitOption,
        verbose_name="opção escolhida",
        on_delete=models.PROTECT,
        related_name="registration_selections",
    )

    created_at = models.DateTimeField(
        verbose_name="criada em",
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        verbose_name="atualizada em",
        auto_now=True,
    )

    class Meta:
        db_table = "kits_registration_selection"
        verbose_name = "escolha individual de kit"
        verbose_name_plural = "escolhas individuais de kits"
        ordering = (
            "registration",
            "kit",
        )
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "registration",
                    "kit",
                ),
                name="kits_registration_kit_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=(
                    "option",
                    "registration",
                ),
                name="kits_selection_option_idx",
            ),
            models.Index(
                fields=(
                    "registration",
                    "kit",
                ),
                name="kits_selection_reg_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.registration} — "
            f"{self.kit.name}: {self.option.name}"
        )

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.kit_id
            and self.option_id
            and self.option.kit_id != self.kit_id
        ):
            errors["option"] = (
                "A opção escolhida não pertence ao kit informado."
            )

        if self.registration_id and self.kit_id:
            registration_event_id = (
                self.registration
                .order_item
                .order
                .event_id
            )

            registration_ticket_type_id = (
                self.registration
                .order_item
                .ticket_type_id
            )

            if self.kit.event_id != registration_event_id:
                errors["kit"] = (
                    "O kit não pertence ao evento da inscrição."
                )
            elif not TicketTypeKit.objects.filter(
                kit_id=self.kit_id,
                ticket_type_id=registration_ticket_type_id,
            ).exists():
                errors["kit"] = (
                    "Este kit não está vinculado ao tipo de "
                    "ingresso da inscrição."
                )

        if errors:
            raise ValidationError(errors)