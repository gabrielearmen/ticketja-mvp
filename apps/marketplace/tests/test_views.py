from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.marketplace.services import AuthorizationStart
from apps.organizations.models import (
    MembershipRole,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)


class MarketplacePaymentAccountViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(
            email="owner-view@example.com",
            password="Senha-Segura!2026",
        )
        cls.admin_user = get_user_model().objects.create_user(
            email="admin-view@example.com",
            password="Senha-Segura!2026",
        )
        cls.organization = Organization.objects.create(
            name="Organização View",
            slug="organizacao-view",
            status=OrganizationStatus.APPROVED,
        )
        OrganizationMembership.objects.create(
            organization=cls.organization,
            user=cls.owner,
            role=MembershipRole.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=cls.organization,
            user=cls.admin_user,
            role=MembershipRole.ADMIN,
        )

    def test_payment_account_page_requires_organizer(self):
        response = self.client.get(
            reverse("marketplace:payment-account")
        )
        self.assertEqual(response.status_code, 302)

    def test_owner_can_view_payment_account_page(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("marketplace:payment-account")
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recebimentos")

    @override_settings(MARKETPLACE_OAUTH_ENABLED=True)
    @patch("apps.marketplace.views.begin_mercado_pago_connection")
    def test_connect_is_post_only_and_redirects_to_provider(
        self,
        mocked_begin,
    ):
        mocked_begin.return_value = AuthorizationStart(
            authorization_url="https://auth.mercadopago.com/authorization",
            expires_at=None,
        )
        self.client.force_login(self.owner)
        url = reverse("marketplace:mercado-pago-connect")

        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            "https://auth.mercadopago.com/authorization",
        )

    @override_settings(MARKETPLACE_OAUTH_ENABLED=True)
    def test_admin_cannot_manage_financial_connection(self):
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse("marketplace:mercado-pago-connect")
        )
        self.assertEqual(response.status_code, 403)
