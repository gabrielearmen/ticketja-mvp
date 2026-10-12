from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.marketplace.models import (
    OrganizationPaymentAccount,
    PaymentAccountStatus,
)
from apps.organizations.models import Organization


class OrganizationPaymentAccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(
            name="Corridas Seguras",
            slug="corridas-seguras",
        )
        cls.user = get_user_model().objects.create_user(
            email="financeiro@example.com",
            password="Senha-Segura!2026",
        )

    def test_one_payment_account_per_organization(self):
        OrganizationPaymentAccount.objects.create(
            organization=self.organization,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationPaymentAccount.objects.create(
                organization=self.organization,
            )

    def test_active_account_requires_receiver_and_encrypted_token(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationPaymentAccount.objects.create(
                organization=self.organization,
                status=PaymentAccountStatus.ACTIVE,
                provider_user_id="123456",
                connected_at=timezone.now(),
            )

    def test_usable_account_never_exposes_token_in_string(self):
        account = OrganizationPaymentAccount.objects.create(
            organization=self.organization,
            status=PaymentAccountStatus.ACTIVE,
            provider_user_id="123456",
            access_token_ciphertext="ciphertext-value",
            connected_at=timezone.now(),
        )

        self.assertTrue(account.is_usable)
        self.assertNotIn(
            "ciphertext-value",
            str(account),
        )
