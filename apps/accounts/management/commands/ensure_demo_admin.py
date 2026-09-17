import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Cria de forma idempotente o administrador demonstrativo "
        "utilizando variáveis protegidas do ambiente."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        email = os.environ.get(
            "TICKETJA_ADMIN_EMAIL",
            "",
        ).strip()

        password = os.environ.get(
            "TICKETJA_ADMIN_PASSWORD",
            "",
        )

        if not email:
            raise CommandError(
                "TICKETJA_ADMIN_EMAIL não foi configurada."
            )

        if not password:
            raise CommandError(
                "TICKETJA_ADMIN_PASSWORD não foi configurada."
            )

        user_model = get_user_model()

        normalized_email = (
            user_model.objects.normalize_email(email)
            .strip()
            .casefold()
        )

        existing_user = (
            user_model.objects
            .select_for_update()
            .filter(email__iexact=normalized_email)
            .first()
        )

        if existing_user is not None:
            if not (
                existing_user.is_active
                and existing_user.is_staff
                and existing_user.is_superuser
            ):
                raise CommandError(
                    "Já existe uma conta com esse e-mail, mas ela "
                    "não é um administrador ativo. A operação foi "
                    "interrompida para impedir elevação automática "
                    "de privilégios."
                )

            self.stdout.write(
                self.style.SUCCESS(
                    "O administrador demonstrativo já existe. "
                    "Nenhuma alteração foi realizada."
                )
            )
            return

        administrator = user_model(
            email=normalized_email,
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )

        try:
            validate_password(
                password,
                user=administrator,
            )
        except ValidationError as error:
            messages = " ".join(error.messages)
            raise CommandError(
                f"A senha do administrador não é válida: {messages}"
            ) from error

        administrator.set_password(password)
        administrator.full_clean()
        administrator.save()

        self.stdout.write(
            self.style.SUCCESS(
                "Administrador demonstrativo criado com sucesso."
            )
        )