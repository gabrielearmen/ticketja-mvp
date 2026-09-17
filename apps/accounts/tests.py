import uuid

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

import os
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from .tokens import account_activation_token

class UserModelTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()

    def test_create_user_with_normalized_email_and_uuid(self):
        user = self.user_model.objects.create_user(
            email="  Pessoa@Example.COM  ",
            password="Senha-Teste!2026",
        )

        self.assertEqual(user.email, "pessoa@example.com")
        self.assertIsInstance(user.id, uuid.UUID)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)

    def test_password_is_not_stored_as_plain_text(self):
        raw_password = "Senha-Teste!2026"

        user = self.user_model.objects.create_user(
            email="pessoa@example.com",
            password=raw_password,
        )

        self.assertNotEqual(user.password, raw_password)
        self.assertTrue(user.check_password(raw_password))
        self.assertFalse(user.check_password("senha-incorreta"))

    def test_email_is_required(self):
        with self.assertRaisesMessage(
            ValueError,
            "O endereço de e-mail é obrigatório.",
        ):
            self.user_model.objects.create_user(
                email="",
                password="Senha-Teste!2026",
            )

    def test_exact_duplicate_email_is_rejected(self):
        self.user_model.objects.create_user(
            email="pessoa@example.com",
            password="Senha-Teste!2026",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.user_model.objects.create_user(
                email="pessoa@example.com",
                password="Outra-Senha!2026",
            )

    def test_case_insensitive_duplicate_email_is_rejected_by_database(self):
        self.user_model.objects.create_user(
            email="pessoa@example.com",
            password="Senha-Teste!2026",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.user_model.objects.create(
                email="PESSOA@EXAMPLE.COM",
            )

    def test_create_superuser_with_administrative_permissions(self):
        user = self.user_model.objects.create_superuser(
            email="admin@example.com",
            password="Senha-Administrativa!2026",
        )

        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_active)

    def test_superuser_rejects_missing_staff_permission(self):
        with self.assertRaisesMessage(
            ValueError,
            "Um superusuário precisa possuir is_staff=True.",
        ):
            self.user_model.objects.create_superuser(
                email="admin@example.com",
                password="Senha-Administrativa!2026",
                is_staff=False,
            )

    def test_superuser_rejects_missing_superuser_permission(self):
        with self.assertRaisesMessage(
            ValueError,
            "Um superusuário precisa possuir is_superuser=True.",
        ):
            self.user_model.objects.create_superuser(
                email="admin@example.com",
                password="Senha-Administrativa!2026",
                is_superuser=False,
            )
class LoginViewTests(TestCase):
    def setUp(self):
        self.password = "Senha-Segura!2026"

        self.user = get_user_model().objects.create_user(
            email="pessoa@example.com",
            password=self.password,
        )

    def test_login_page_is_available(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "accounts/login.html",
        )
        self.assertContains(response, "Entre na sua conta.")

    def test_user_can_login_with_email_and_password(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": self.user.email,
                "password": self.password,
            },
        )

        self.assertRedirects(
            response,
            reverse("core:home"),
        )

        self.assertEqual(
            self.client.session["_auth_user_id"],
            str(self.user.pk),
        )

    def test_email_login_is_case_insensitive(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "PESSOA@EXAMPLE.COM",
                "password": self.password,
            },
        )

        self.assertRedirects(
            response,
            reverse("core:home"),
        )

    def test_invalid_credentials_show_generic_error(self):
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": self.user.email,
                "password": "senha-incorreta",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Não foi possível entrar com os dados informados.",
        )
        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
        )

    def test_inactive_user_cannot_login(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": self.user.email,
                "password": self.password,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
        )

    def test_authenticated_user_is_redirected_from_login(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:login"))

        self.assertRedirects(
            response,
            reverse("core:home"),
        )

    def test_logout_requires_post(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("accounts:logout"))

        self.assertEqual(response.status_code, 405)

    def test_post_logout_ends_session(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(
            response,
            reverse("core:home"),
        )
        self.assertNotIn(
            "_auth_user_id",
            self.client.session,
        )

@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="TicketJá <nao-responda@ticketja.local>",
)
class RegistrationFlowTests(TestCase):
    def setUp(self):
        self.registration_data = {
            "first_name": "Pessoa",
            "last_name": "Teste",
            "email": "pessoa@example.com",
            "password1": "Uma-Senha-Forte!2026",
            "password2": "Uma-Senha-Forte!2026",
        }

    def test_registration_page_is_available(self):
        response = self.client.get(reverse("accounts:register"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "accounts/register.html",
        )
        self.assertContains(response, "Crie sua conta.")

    def test_registration_creates_inactive_user_and_sends_email(self):
        response = self.client.post(
            reverse("accounts:register"),
            self.registration_data,
        )

        self.assertRedirects(
            response,
            reverse("accounts:registration_done"),
        )

        user = get_user_model().objects.get(
            email="pessoa@example.com",
        )

        self.assertFalse(user.is_active)
        self.assertTrue(
            user.check_password("Uma-Senha-Forte!2026")
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].to,
            ["pessoa@example.com"],
        )
        self.assertIn(
            "/confirmar-email/",
            mail.outbox[0].body,
        )

    def test_duplicate_email_is_rejected_case_insensitively(self):
        get_user_model().objects.create_user(
            email="pessoa@example.com",
            password="Outra-Senha-Forte!2026",
        )

        duplicate_data = {
            **self.registration_data,
            "email": "PESSOA@EXAMPLE.COM",
        }

        response = self.client.post(
            reverse("accounts:register"),
            duplicate_data,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Não foi possível concluir o cadastro com este e-mail.",
        )
        self.assertEqual(
            get_user_model().objects.count(),
            1,
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_password_confirmation_must_match(self):
        invalid_data = {
            **self.registration_data,
            "password2": "Senha-Diferente!2026",
        }

        response = self.client.post(
            reverse("accounts:register"),
            invalid_data,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Os dois campos de senha não correspondem",
        )
        self.assertFalse(
            get_user_model().objects.exists()
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_valid_activation_enables_account(self):
        user = get_user_model().objects.create_user(
            email="pessoa@example.com",
            password="Uma-Senha-Forte!2026",
            is_active=False,
        )

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = account_activation_token.make_token(user)

        response = self.client.get(
            reverse(
                "accounts:activate",
                kwargs={
                    "uidb64": uid,
                    "token": token,
                },
            )
        )

        self.assertRedirects(
            response,
            reverse("accounts:login"),
        )

        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_activation_token_cannot_be_reused(self):
        user = get_user_model().objects.create_user(
            email="pessoa@example.com",
            password="Uma-Senha-Forte!2026",
            is_active=False,
        )

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = account_activation_token.make_token(user)

        activation_url = reverse(
            "accounts:activate",
            kwargs={
                "uidb64": uid,
                "token": token,
            },
        )

        first_response = self.client.get(activation_url)
        second_response = self.client.get(activation_url)

        self.assertRedirects(
            first_response,
            reverse("accounts:login"),
        )
        self.assertEqual(second_response.status_code, 400)

    def test_invalid_activation_token_does_not_enable_account(self):
        user = get_user_model().objects.create_user(
            email="pessoa@example.com",
            password="Uma-Senha-Forte!2026",
            is_active=False,
        )

        uid = urlsafe_base64_encode(force_bytes(user.pk))

        response = self.client.get(
            reverse(
                "accounts:activate",
                kwargs={
                    "uidb64": uid,
                    "token": "token-invalido",
                },
            )
        )

        self.assertEqual(response.status_code, 400)

        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_authenticated_user_is_redirected_from_registration(self):
        user = get_user_model().objects.create_user(
            email="pessoa@example.com",
            password="Uma-Senha-Forte!2026",
        )

        self.client.force_login(user)

        response = self.client.get(
            reverse("accounts:register")
        )

        self.assertRedirects(
            response,
            reverse("core:home"),
        )

class EnsureDemoAdminCommandTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.email = "admin-demo@example.com"
        self.password = "Senha-Demonstrativa!2026"

    def run_command(self):
        output = StringIO()

        call_command(
            "ensure_demo_admin",
            stdout=output,
        )

        return output.getvalue()

    def test_command_requires_environment_variables(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CommandError):
                self.run_command()

    def test_command_creates_active_superuser(self):
        environment = {
            "TICKETJA_ADMIN_EMAIL": self.email,
            "TICKETJA_ADMIN_PASSWORD": self.password,
        }

        with patch.dict(
            os.environ,
            environment,
            clear=False,
        ):
            output = self.run_command()

        administrator = self.user_model.objects.get(
            email=self.email,
        )

        self.assertTrue(administrator.is_active)
        self.assertTrue(administrator.is_staff)
        self.assertTrue(administrator.is_superuser)
        self.assertTrue(
            administrator.check_password(self.password)
        )
        self.assertIn(
            "criado com sucesso",
            output.lower(),
        )

    def test_command_is_idempotent(self):
        environment = {
            "TICKETJA_ADMIN_EMAIL": self.email,
            "TICKETJA_ADMIN_PASSWORD": self.password,
        }

        with patch.dict(
            os.environ,
            environment,
            clear=False,
        ):
            self.run_command()
            output = self.run_command()

        self.assertEqual(
            self.user_model.objects.filter(
                email=self.email,
            ).count(),
            1,
        )
        self.assertIn(
            "já existe",
            output.lower(),
        )

    def test_command_refuses_privilege_escalation(self):
        self.user_model.objects.create_user(
            email=self.email,
            password=self.password,
        )

        environment = {
            "TICKETJA_ADMIN_EMAIL": self.email,
            "TICKETJA_ADMIN_PASSWORD": self.password,
        }

        with patch.dict(
            os.environ,
            environment,
            clear=False,
        ):
            with self.assertRaises(CommandError):
                self.run_command()

        user = self.user_model.objects.get(
            email=self.email,
        )

        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)