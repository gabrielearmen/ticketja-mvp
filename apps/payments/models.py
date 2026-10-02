import secrets
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


MONEY_ZERO = Decimal("0.00")

PAYMENT_REFERENCE_ALPHABET = (
    "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
)


def generate_payment_external_reference():
    """
    Gera uma referência pública não sequencial.

    Essa referência poderá ser enviada ao provedor sem revelar
    o identificador interno do pedido ou dados do comprador.
    """
    random_part = "".join(
        secrets.choice(PAYMENT_REFERENCE_ALPHABET)
        for _ in range(18)
    )

    return f"TJP-{random_part}"


class PaymentProvider(models.TextChoices):
    INTERNAL = "interno", "Processamento interno"
    MERCADO_PAGO = "mercado_pago", "Mercado Pago"


class PaymentMethod(models.TextChoices):
    FREE = "gratuito", "Gratuito"
    PIX = "pix", "PIX"
    BOLETO = "boleto", "Boleto"
    CARD = "cartao", "Cartão"


class PaymentStatus(models.TextChoices):
    CREATED = "criado", "Criado"
    PENDING = "pendente", "Pendente"
    APPROVED = "aprovado", "Aprovado"
    REJECTED = "rejeitado", "Rejeitado"
    CANCELED = "cancelado", "Cancelado"
    REFUNDED = "reembolsado", "Reembolsado"
    EXPIRED = "expirado", "Expirado"
    ERROR = "erro", "Erro"


OPEN_PAYMENT_STATUSES = (
    PaymentStatus.CREATED,
    PaymentStatus.PENDING,
)


class PaymentQuerySet(models.QuerySet):
    def for_order(self, order):
        return self.filter(order=order)

    def open(self):
        return self.filter(
            status__in=OPEN_PAYMENT_STATUSES,
        )

    def approved(self):
        return self.filter(
            status=PaymentStatus.APPROVED,
        )

    def for_provider(self, provider):
        return self.filter(provider=provider)


class Payment(models.Model):
    """
    Representa uma tentativa de pagamento.

    Um pedido pode possuir várias tentativas rejeitadas,
    canceladas ou expiradas, mas somente uma tentativa aberta
    e somente um pagamento aprovado.

    Nenhum dado de cartão é armazenado neste modelo.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    order = models.ForeignKey(
        "orders.Order",
        verbose_name="pedido",
        on_delete=models.PROTECT,
        related_name="payments",
    )

    attempt_number = models.PositiveSmallIntegerField(
        verbose_name="número da tentativa",
    )

    idempotency_key = models.UUIDField(
        verbose_name="chave de idempotência",
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    external_reference = models.CharField(
        verbose_name="referência externa",
        max_length=32,
        default=generate_payment_external_reference,
        unique=True,
        editable=False,
    )

    provider = models.CharField(
        verbose_name="provedor",
        max_length=30,
        choices=PaymentProvider.choices,
    )

    method = models.CharField(
        verbose_name="meio de pagamento",
        max_length=20,
        choices=PaymentMethod.choices,
    )

    status = models.CharField(
        verbose_name="situação",
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.CREATED,
    )

    amount = models.DecimalField(
        verbose_name="valor da cobrança",
        max_digits=14,
        decimal_places=2,
    )

    platform_fee = models.DecimalField(
        verbose_name="comissão da plataforma",
        max_digits=14,
        decimal_places=2,
        default=MONEY_ZERO,
    )

    provider_fee = models.DecimalField(
        verbose_name="tarifa do provedor",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )

    net_amount = models.DecimalField(
        verbose_name="valor líquido",
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )

    provider_account_reference = models.CharField(
        verbose_name="referência da conta recebedora",
        max_length=255,
        blank=True,
    )

    provider_order_id = models.CharField(
        verbose_name="identificador da ordem no provedor",
        max_length=255,
        blank=True,
    )

    provider_payment_id = models.CharField(
        verbose_name="identificador do pagamento no provedor",
        max_length=255,
        blank=True,
    )

    provider_status = models.CharField(
        verbose_name="situação informada pelo provedor",
        max_length=100,
        blank=True,
    )

    provider_status_detail = models.CharField(
        verbose_name="detalhe da situação no provedor",
        max_length=255,
        blank=True,
    )

    checkout_url = models.URLField(
        verbose_name="endereço de pagamento",
        max_length=1000,
        blank=True,
    )

    pix_copy_paste = models.TextField(
        verbose_name="PIX copia e cola",
        blank=True,
    )

    pix_qr_code_base64 = models.TextField(
        verbose_name="QR Code PIX em base64",
        blank=True,
    )

    failure_code = models.CharField(
        verbose_name="código da falha",
        max_length=100,
        blank=True,
    )

    failure_message = models.CharField(
        verbose_name="mensagem sanitizada da falha",
        max_length=500,
        blank=True,
    )

    expires_at = models.DateTimeField(
        verbose_name="expiração da cobrança",
        null=True,
        blank=True,
    )

    approved_at = models.DateTimeField(
        verbose_name="aprovado em",
        null=True,
        blank=True,
    )

    canceled_at = models.DateTimeField(
        verbose_name="cancelado em",
        null=True,
        blank=True,
    )

    refunded_at = models.DateTimeField(
        verbose_name="reembolsado em",
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

    objects = PaymentQuerySet.as_manager()

    class Meta:
        db_table = "payments_payment"
        verbose_name = "pagamento"
        verbose_name_plural = "pagamentos"
        ordering = (
            "-created_at",
            "-attempt_number",
        )
        constraints = [
            models.CheckConstraint(
                condition=models.Q(attempt_number__gt=0),
                name="pay_attempt_gt_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gte=MONEY_ZERO),
                name="pay_amount_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    platform_fee__gte=MONEY_ZERO,
                ),
                name="pay_platform_fee_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    platform_fee__lte=models.F("amount"),
                ),
                name="pay_platform_fee_lte_amount",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(provider_fee__isnull=True)
                    | models.Q(provider_fee__gte=MONEY_ZERO)
                ),
                name="pay_provider_fee_gte_zero",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(net_amount__isnull=True)
                    | models.Q(net_amount__gte=MONEY_ZERO)
                ),
                name="pay_net_amount_gte_zero",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    provider__in=PaymentProvider.values,
                ),
                name="pay_provider_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    method__in=PaymentMethod.values,
                ),
                name="pay_method_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=PaymentStatus.values,
                ),
                name="pay_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        provider=PaymentProvider.INTERNAL,
                        method=PaymentMethod.FREE,
                        amount=MONEY_ZERO,
                    )
                    | (
                        ~models.Q(
                            provider=PaymentProvider.INTERNAL,
                        )
                        & ~models.Q(
                            method=PaymentMethod.FREE,
                        )
                        & models.Q(amount__gt=MONEY_ZERO)
                    )
                ),
                name="pay_free_consistency",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(
                        status=PaymentStatus.APPROVED,
                    )
                    | models.Q(approved_at__isnull=False)
                ),
                name="pay_approved_timestamp",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(
                        status=PaymentStatus.CANCELED,
                    )
                    | models.Q(canceled_at__isnull=False)
                ),
                name="pay_canceled_timestamp",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(
                        status=PaymentStatus.REFUNDED,
                    )
                    | models.Q(refunded_at__isnull=False)
                ),
                name="pay_refunded_timestamp",
            ),
            models.UniqueConstraint(
                fields=(
                    "order",
                    "attempt_number",
                ),
                name="pay_order_attempt_unique",
            ),
            models.UniqueConstraint(
                fields=(
                    "provider",
                    "provider_order_id",
                ),
                condition=~models.Q(
                    provider_order_id="",
                ),
                name="pay_provider_order_unique",
            ),
            models.UniqueConstraint(
                fields=(
                    "provider",
                    "provider_payment_id",
                ),
                condition=~models.Q(
                    provider_payment_id="",
                ),
                name="pay_provider_payment_unique",
            ),
            models.UniqueConstraint(
                fields=("order",),
                condition=models.Q(
                    status__in=OPEN_PAYMENT_STATUSES,
                ),
                name="pay_one_open_attempt",
            ),
            models.UniqueConstraint(
                fields=("order",),
                condition=models.Q(
                    status=PaymentStatus.APPROVED,
                ),
                name="pay_one_approved_attempt",
            ),
        ]
        indexes = [
            models.Index(
                fields=(
                    "order",
                    "status",
                    "created_at",
                ),
                name="pay_order_status_created_idx",
            ),
            models.Index(
                fields=(
                    "provider",
                    "provider_payment_id",
                ),
                name="pay_provider_payment_idx",
            ),
            models.Index(
                fields=(
                    "status",
                    "expires_at",
                ),
                name="pay_status_expiry_idx",
            ),
            models.Index(
                fields=(
                    "external_reference",
                    "provider",
                ),
                name="pay_reference_provider_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.external_reference} — "
            f"{self.get_status_display()}"
        )

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.order_id
            and self.amount is not None
            and self.amount != self.order.total
        ):
            errors["amount"] = (
                "O valor do pagamento deve ser igual "
                "ao total congelado no pedido."
            )

        if (
            self.platform_fee is not None
            and self.amount is not None
            and self.platform_fee > self.amount
        ):
            errors["platform_fee"] = (
                "A comissão da plataforma não pode superar "
                "o valor do pagamento."
            )

        is_free_payment = (
            self.provider == PaymentProvider.INTERNAL
            and self.method == PaymentMethod.FREE
            and self.amount == MONEY_ZERO
        )

        is_external_payment = (
            self.provider != PaymentProvider.INTERNAL
            and self.method != PaymentMethod.FREE
            and self.amount is not None
            and self.amount > MONEY_ZERO
        )

        if not is_free_payment and not is_external_payment:
            errors["method"] = (
                "Pedidos gratuitos devem utilizar processamento "
                "interno. Pagamentos externos devem possuir "
                "valor maior que zero."
            )

        timestamp_requirements = {
            PaymentStatus.APPROVED: (
                "approved_at",
                self.approved_at,
                "Informe quando o pagamento foi aprovado.",
            ),
            PaymentStatus.CANCELED: (
                "canceled_at",
                self.canceled_at,
                "Informe quando o pagamento foi cancelado.",
            ),
            PaymentStatus.REFUNDED: (
                "refunded_at",
                self.refunded_at,
                "Informe quando o pagamento foi reembolsado.",
            ),
        }

        requirement = timestamp_requirements.get(self.status)

        if requirement is not None:
            field_name, value, message = requirement

            if value is None:
                errors[field_name] = message

        if errors:
            raise ValidationError(errors)

    @property
    def is_open(self):
        return self.status in OPEN_PAYMENT_STATUSES

    @property
    def is_terminal(self):
        return self.status in {
            PaymentStatus.APPROVED,
            PaymentStatus.REJECTED,
            PaymentStatus.CANCELED,
            PaymentStatus.REFUNDED,
            PaymentStatus.EXPIRED,
            PaymentStatus.ERROR,
        }

    @property
    def has_expired(self):
        return (
            self.expires_at is not None
            and self.expires_at <= timezone.now()
            and self.status in OPEN_PAYMENT_STATUSES
        )


class WebhookProcessingStatus(models.TextChoices):
    RECEIVED = "recebido", "Recebido"
    PROCESSED = "processado", "Processado"
    IGNORED = "ignorado", "Ignorado"
    FAILED = "falhou", "Falhou"


SHA256_VALIDATOR = RegexValidator(
    regex=r"^[0-9a-f]{64}$",
    message=(
        "O resumo deve ser um SHA-256 hexadecimal "
        "em letras minúsculas."
    ),
)


class PaymentWebhookEventQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(
            processing_status=(
                WebhookProcessingStatus.RECEIVED
            ),
        )

    def for_provider(self, provider):
        return self.filter(provider=provider)

    def for_resource(self, resource_id):
        return self.filter(resource_id=resource_id)


class PaymentWebhookEvent(models.Model):
    """
    Registro mínimo e seguro de uma notificação de pagamento.

    O corpo completo do webhook não é armazenado. Guardamos apenas
    identificadores necessários, resultado da autenticação e o
    hash SHA-256 do conteúdo recebido.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    payment = models.ForeignKey(
        Payment,
        verbose_name="pagamento",
        on_delete=models.SET_NULL,
        related_name="webhook_events",
        null=True,
        blank=True,
    )

    provider = models.CharField(
        verbose_name="provedor",
        max_length=30,
        choices=PaymentProvider.choices,
    )

    notification_id = models.CharField(
        verbose_name="identificador da notificação",
        max_length=255,
    )

    event_type = models.CharField(
        verbose_name="tipo do evento",
        max_length=100,
    )

    action = models.CharField(
        verbose_name="ação",
        max_length=100,
        blank=True,
    )

    resource_id = models.CharField(
        verbose_name="identificador do recurso",
        max_length=255,
    )

    request_id = models.CharField(
        verbose_name="identificador da requisição",
        max_length=255,
        blank=True,
    )

    deduplication_key = models.CharField(
        verbose_name="chave de deduplicação",
        max_length=64,
        unique=True,
        editable=False,
        validators=[SHA256_VALIDATOR],
    )

    payload_sha256 = models.CharField(
        verbose_name="SHA-256 do conteúdo",
        max_length=64,
        validators=[SHA256_VALIDATOR],
    )

    signature_valid = models.BooleanField(
        verbose_name="assinatura válida",
        default=False,
    )

    processing_status = models.CharField(
        verbose_name="situação do processamento",
        max_length=20,
        choices=WebhookProcessingStatus.choices,
        default=WebhookProcessingStatus.RECEIVED,
    )

    processing_attempts = models.PositiveSmallIntegerField(
        verbose_name="tentativas de processamento",
        default=0,
    )

    failure_reason = models.CharField(
        verbose_name="motivo sanitizado da falha",
        max_length=500,
        blank=True,
    )

    received_at = models.DateTimeField(
        verbose_name="recebido em",
        auto_now_add=True,
    )

    processed_at = models.DateTimeField(
        verbose_name="processado em",
        null=True,
        blank=True,
    )

    updated_at = models.DateTimeField(
        verbose_name="atualizado em",
        auto_now=True,
    )

    objects = PaymentWebhookEventQuerySet.as_manager()

    class Meta:
        db_table = "payments_webhook_event"
        verbose_name = "evento de webhook"
        verbose_name_plural = "eventos de webhook"
        ordering = ("-received_at",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    provider__in=PaymentProvider.values,
                ),
                name="pay_webhook_provider_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    processing_status__in=(
                        WebhookProcessingStatus.values
                    ),
                ),
                name="pay_webhook_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    processing_attempts__gte=0,
                ),
                name="pay_webhook_attempts_gte_zero",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(
                            processing_status=(
                                WebhookProcessingStatus.RECEIVED
                            ),
                        )
                        & models.Q(
                            processed_at__isnull=True,
                        )
                    )
                    | (
                        ~models.Q(
                            processing_status=(
                                WebhookProcessingStatus.RECEIVED
                            ),
                        )
                        & models.Q(
                            processed_at__isnull=False,
                        )
                    )
                ),
                name="pay_webhook_processed_at_valid",
            ),
            models.UniqueConstraint(
                fields=(
                    "provider",
                    "notification_id",
                ),
                name="pay_webhook_notification_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=(
                    "provider",
                    "resource_id",
                ),
                name="pay_webhook_resource_idx",
            ),
            models.Index(
                fields=(
                    "processing_status",
                    "received_at",
                ),
                name="pay_wh_status_received_idx",
            ),
            models.Index(
                fields=(
                    "payment",
                    "received_at",
                ),
                name="pay_webhook_payment_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.provider} — "
            f"{self.notification_id}"
        )