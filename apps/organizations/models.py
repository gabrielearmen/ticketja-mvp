import uuid

from django.conf import settings
from django.db import models


class OrganizationStatus(models.TextChoices):
    PENDING = "pending", "Aguardando aprovação"
    APPROVED = "approved", "Aprovada"
    SUSPENDED = "suspended", "Suspensa"


class MembershipRole(models.TextChoices):
    OWNER = "owner", "Proprietário"
    ADMIN = "admin", "Administrador"


class Organization(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    name = models.CharField(
        verbose_name="nome",
        max_length=150,
    )

    slug = models.SlugField(
        verbose_name="identificador público",
        max_length=160,
        unique=True,
    )

    status = models.CharField(
        verbose_name="situação",
        max_length=20,
        choices=OrganizationStatus.choices,
        default=OrganizationStatus.PENDING,
        db_index=True,
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
        db_table = "organizations_organization"
        verbose_name = "organização"
        verbose_name_plural = "organizações"
        ordering = ("name",)

    def __str__(self):
        return self.name


class OrganizationMembership(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    organization = models.ForeignKey(
        Organization,
        verbose_name="organização",
        on_delete=models.PROTECT,
        related_name="memberships",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="usuário",
        on_delete=models.PROTECT,
        related_name="organization_memberships",
    )

    role = models.CharField(
        verbose_name="papel",
        max_length=20,
        choices=MembershipRole.choices,
        default=MembershipRole.ADMIN,
    )

    is_active = models.BooleanField(
        verbose_name="vínculo ativo",
        default=True,
    )

    created_at = models.DateTimeField(
        verbose_name="criado em",
        auto_now_add=True,
    )

    class Meta:
        db_table = "organizations_membership"
        verbose_name = "membro da organização"
        verbose_name_plural = "membros das organizações"
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "user"),
                name="organization_membership_user_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "is_active"),
                name="org_member_user_active_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user.email} — {self.organization.name}"