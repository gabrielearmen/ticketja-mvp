import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class DocumentType(models.TextChoices):
    CPF = "cpf", "CPF"
    PASSPORT = "passaporte", "Passaporte"
    OTHER = "outro", "Outro documento"


class Registration(models.Model):
    """
    Representa uma inscrição individual.

    Um OrderItem pode possuir várias inscrições, de acordo com
    a quantidade comprada. A posição identifica cada ingresso:
    participante 1, participante 2 e assim por diante.

    O status financeiro não é duplicado aqui. Ele permanece no
    pedido, evitando inconsistências entre pagamento e inscrição.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    order_item = models.ForeignKey(
        "orders.OrderItem",
        verbose_name="item do pedido",
        on_delete=models.PROTECT,
        related_name="registrations",
    )

    position = models.PositiveIntegerField(
        verbose_name="posição no item",
    )

    full_name = models.CharField(
        verbose_name="nome completo",
        max_length=160,
        blank=True,
    )

    document_type = models.CharField(
        verbose_name="tipo de documento",
        max_length=20,
        choices=DocumentType.choices,
        default=DocumentType.CPF,
    )

    document_number = models.CharField(
        verbose_name="número do documento",
        max_length=40,
        blank=True,
    )

    birth_date = models.DateField(
        verbose_name="data de nascimento",
        null=True,
        blank=True,
    )

    email = models.EmailField(
        verbose_name="e-mail do participante",
        blank=True,
    )

    phone = models.CharField(
        verbose_name="telefone do participante",
        max_length=20,
        blank=True,
    )

    emergency_contact_name = models.CharField(
        verbose_name="contato de emergência",
        max_length=160,
        blank=True,
    )

    emergency_contact_phone = models.CharField(
        verbose_name="telefone de emergência",
        max_length=20,
        blank=True,
    )

    completed_at = models.DateTimeField(
        verbose_name="dados concluídos em",
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

    class Meta:
        db_table = "registrations_registration"
        verbose_name = "inscrição"
        verbose_name_plural = "inscrições"
        ordering = (
            "order_item",
            "position",
        )
        constraints = [
            models.CheckConstraint(
                condition=models.Q(position__gt=0),
                name="reg_position_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    document_type__in=DocumentType.values,
                ),
                name="reg_document_type_valid",
            ),
            models.UniqueConstraint(
                fields=(
                    "order_item",
                    "position",
                ),
                name="reg_item_position_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(completed_at__isnull=True)
                    | (
                        ~models.Q(full_name="")
                        & ~models.Q(document_number="")
                        & models.Q(birth_date__isnull=False)
                    )
                ),
                name="reg_completed_data_required",
            ),
        ]

    def __str__(self):
        participant = self.full_name or (
            f"Participante {self.position}"
        )

        return (
            f"{self.order_item.order.public_code} — "
            f"{participant}"
        )

    def clean(self):
        super().clean()

        errors = {}

        self.full_name = " ".join(
            self.full_name.split()
        )

        self.document_number = (
            self.document_number.strip().upper()
        )

        self.email = self.email.strip().lower()

        if (
            self.birth_date is not None
            and self.birth_date >= timezone.localdate()
        ):
            errors["birth_date"] = (
                "A data de nascimento deve ser anterior "
                "à data atual."
            )

        if self.completed_at is not None:
            required_fields = {
                "full_name": self.full_name,
                "document_number": self.document_number,
                "birth_date": self.birth_date,
            }

            for field_name, value in required_fields.items():
                if not value:
                    errors[field_name] = (
                        "Preencha este campo para concluir "
                        "a inscrição."
                    )

        if errors:
            raise ValidationError(errors)

    @property
    def is_complete(self):
        return (
            self.completed_at is not None
            and bool(self.full_name)
            and bool(self.document_number)
            and self.birth_date is not None
        )

    @property
    def order(self):
        return self.order_item.order

    @property
    def event(self):
        return self.order_item.order.event

    @property
    def organization(self):
        return self.order_item.order.organization