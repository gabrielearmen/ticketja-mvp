import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


MONEY_ZERO = Decimal("0.00")
PERCENT_ZERO = Decimal("0.0000")
PERCENT_MAX = Decimal("100.0000")
COMMERCIAL_PERCENT_MIN = Decimal("8.0000")
COMMERCIAL_PERCENT_MAX = Decimal("10.0000")


class MarketplaceProvider(models.TextChoices):
    MERCADO_PAGO = "mercado_pago", "Mercado Pago"


class PaymentAccountStatus(models.TextChoices):
    DISCONNECTED = "disconnected", "Não conectada"
    PENDING = "pending", "Conexão pendente"
    ACTIVE = "active", "Ativa"
    REAUTH_REQUIRED = "reauth_required", "Reconexão necessária"
    REVOKED = "revoked", "Revogada"
    BLOCKED = "blocked", "Bloqueada"


class FeeBearer(models.TextChoices):
    BUYER = "buyer", "Comprador"
    ORGANIZER = "organizer", "Organizador"


class OrganizationPaymentAccount(models.Model):
    """
    Conexão financeira de uma organização com o provedor.

    Tokens são persistidos somente em formato criptografado. Nenhuma
    view, template, log ou representação textual deve expô-los.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="payment_account",
        verbose_name="organização",
    )
    provider = models.CharField(
        max_length=30,
        choices=MarketplaceProvider.choices,
        default=MarketplaceProvider.MERCADO_PAGO,
        verbose_name="provedor",
    )
    status = models.CharField(
        max_length=30,
        choices=PaymentAccountStatus.choices,
        default=PaymentAccountStatus.DISCONNECTED,
        verbose_name="situação",
    )
    provider_user_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        unique=True,
        verbose_name="identificador do recebedor",
    )
    is_live_mode = models.BooleanField(
        null=True,
        blank=True,
        verbose_name="conta em produção",
    )
    access_token_ciphertext = models.TextField(
        blank=True,
        editable=False,
        verbose_name="Access Token criptografado",
    )
    refresh_token_ciphertext = models.TextField(
        blank=True,
        editable=False,
        verbose_name="Refresh Token criptografado",
    )
    access_token_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="expiração do Access Token",
    )
    granted_scopes = models.TextField(
        blank=True,
        verbose_name="permissões concedidas",
    )
    connected_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="conectada em",
    )
    last_refreshed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="token renovado em",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="revogada em",
    )
    last_error_code = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="último código de erro",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "marketplace_payment_account"
        verbose_name = "conta recebedora"
        verbose_name_plural = "contas recebedoras"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=PaymentAccountStatus.values),
                name="mkt_acct_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status=PaymentAccountStatus.ACTIVE)
                    | Q(provider_user_id__isnull=False)
                ),
                name="mkt_active_user_required",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status=PaymentAccountStatus.ACTIVE)
                    | ~Q(access_token_ciphertext="")
                ),
                name="mkt_active_token_required",
            ),
        ]
        indexes = [
            models.Index(
                fields=("status", "provider"),
                name="mkt_acct_status_prov_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.organization.name} — "
            f"{self.get_status_display()}"
        )

    @property
    def is_usable(self):
        return (
            self.status == PaymentAccountStatus.ACTIVE
            and bool(self.provider_user_id)
            and bool(self.access_token_ciphertext)
        )


class OAuthAuthorizationAttempt(models.Model):
    """Tentativa curta e de uso único para proteger o retorno OAuth."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="payment_authorization_attempts",
    )
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payment_authorization_attempts",
    )
    state_digest = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
    )
    code_verifier_ciphertext = models.TextField(
        editable=False,
    )
    redirect_uri = models.URLField(max_length=500)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "marketplace_oauth_attempt"
        verbose_name = "tentativa OAuth"
        verbose_name_plural = "tentativas OAuth"
        constraints = [
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")),
                name="mkt_oauth_exp_after_create",
            ),
            models.CheckConstraint(
                condition=(
                    Q(consumed_at__isnull=True)
                    | Q(consumed_at__gte=F("created_at"))
                ),
                name="mkt_oauth_cons_after_create",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "expires_at"),
                name="mkt_oauth_org_exp_idx",
            ),
        ]

    @property
    def is_available(self):
        return (
            self.consumed_at is None
            and self.expires_at > timezone.now()
        )


class MarketplaceFeePolicy(models.Model):
    """Política versionada usada para calcular a comissão."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    name = models.CharField(max_length=120)
    fee_bearer = models.CharField(
        max_length=20,
        choices=FeeBearer.choices,
        default=FeeBearer.BUYER,
    )
    percentage_rate = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=PERCENT_ZERO,
        validators=[
            MinValueValidator(PERCENT_ZERO),
            MaxValueValidator(PERCENT_MAX),
        ],
    )
    fixed_amount_per_ticket = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=MONEY_ZERO,
        validators=[MinValueValidator(MONEY_ZERO)],
    )
    minimum_fee = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(MONEY_ZERO)],
    )
    maximum_fee = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(MONEY_ZERO)],
    )
    effective_from = models.DateTimeField()
    effective_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "marketplace_fee_policy"
        verbose_name = "política de comissão"
        verbose_name_plural = "políticas de comissão"
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    fee_bearer__in=FeeBearer.values,
                ),
                name="mkt_fee_bearer_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(percentage_rate__gte=PERCENT_ZERO)
                    & Q(percentage_rate__lte=PERCENT_MAX)
                ),
                name="mkt_fee_pct_range",
            ),
            models.CheckConstraint(
                condition=Q(fixed_amount_per_ticket__gte=MONEY_ZERO),
                name="mkt_fee_fixed_gte_zero",
            ),
            models.CheckConstraint(
                condition=(
                    Q(effective_until__isnull=True)
                    | Q(effective_until__gt=F("effective_from"))
                ),
                name="mkt_fee_period_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(maximum_fee__isnull=True)
                    | Q(minimum_fee__isnull=True)
                    | Q(maximum_fee__gte=F("minimum_fee"))
                ),
                name="mkt_fee_limits_valid",
            ),
            models.UniqueConstraint(
                fields=("is_active",),
                condition=Q(is_active=True),
                name="mkt_one_active_fee_policy",
            ),
        ]
        indexes = [
            models.Index(
                fields=("is_active", "effective_from"),
                name="mkt_fee_active_start_idx",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()

        errors = {}

        if not (
            COMMERCIAL_PERCENT_MIN
            <= self.percentage_rate
            <= COMMERCIAL_PERCENT_MAX
        ):
            errors["percentage_rate"] = (
                "A comissão deve estar entre 8% e 10%."
            )

        if self.fixed_amount_per_ticket != MONEY_ZERO:
            errors["fixed_amount_per_ticket"] = (
                "A política comercial atual não cobra valor fixo "
                "por ingresso. Informe R$ 0,00."
            )

        if self.minimum_fee is not None or self.maximum_fee is not None:
            errors["minimum_fee"] = (
                "A política atual utiliza somente percentual, sem "
                "valores mínimo ou máximo."
            )

        if errors:
            from django.core.exceptions import ValidationError

            raise ValidationError(errors)
