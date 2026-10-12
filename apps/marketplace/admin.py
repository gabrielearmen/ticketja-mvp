from django.contrib import admin

from .models import (
    MarketplaceFeePolicy,
    OAuthAuthorizationAttempt,
    OrganizationPaymentAccount,
)


@admin.register(OrganizationPaymentAccount)
class OrganizationPaymentAccountAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "provider",
        "status",
        "provider_user_id",
        "is_live_mode",
        "connected_at",
    )
    list_filter = ("provider", "status")
    search_fields = (
        "organization__name",
        "provider_user_id",
    )
    readonly_fields = (
        "provider_user_id",
        "status",
        "is_live_mode",
        "access_token_expires_at",
        "granted_scopes",
        "connected_at",
        "last_refreshed_at",
        "revoked_at",
        "last_error_code",
        "created_at",
        "updated_at",
    )
    exclude = (
        "access_token_ciphertext",
        "refresh_token_ciphertext",
    )


@admin.register(MarketplaceFeePolicy)
class MarketplaceFeePolicyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "fee_bearer",
        "percentage_rate",
        "fixed_amount_per_ticket",
        "is_active",
        "effective_from",
    )
    list_filter = ("is_active", "fee_bearer")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OAuthAuthorizationAttempt)
class OAuthAuthorizationAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "initiated_by",
        "expires_at",
        "consumed_at",
    )
    readonly_fields = (
        "organization",
        "initiated_by",
        "state_digest",
        "redirect_uri",
        "expires_at",
        "consumed_at",
        "created_at",
    )
    exclude = ("code_verifier_ciphertext",)

    def has_add_permission(self, request):
        return False
