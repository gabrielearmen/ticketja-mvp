import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from .managers import UserManager


class User(AbstractUser):
    """
    Identidade autenticável da plataforma.

    Uma conta pode comprar inscrições para vários participantes.
    Participantes não são representados por este modelo.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    username = None

    email = models.EmailField(
        verbose_name="e-mail",
        unique=True,
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "accounts_user"
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="accounts_user_email_case_insensitive_unique",
            ),
        ]

    def __str__(self):
        return self.email