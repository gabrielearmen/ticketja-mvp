from django.contrib import admin

from .models import (
    Payment,
    PaymentWebhookEvent,
)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "external_reference",
        "order",
        "attempt_number",
        "provider",
        "method",
        "status",
        "amount",
        "created_at",
    )

    list_filter = (
        "provider",
        "method",
        "status",
        "created_at",
    )

    search_fields = (
        "external_reference",
        "order__public_code",
        "provider_order_id",
        "provider_payment_id",
        "order__buyer__email",
    )

    ordering = (
        "-created_at",
    )

    readonly_fields = (
        "id",
        "order",
        "attempt_number",
        "idempotency_key",
        "external_reference",
        "provider",
        "method",
        "status",
        "amount",
        "platform_fee",
        "provider_fee",
        "net_amount",
        "provider_account_reference",
        "provider_order_id",
        "provider_payment_id",
        "provider_status",
        "provider_status_detail",
        "checkout_url",
        "pix_copy_paste",
        "pix_qr_code_base64",
        "failure_code",
        "failure_message",
        "expires_at",
        "approved_at",
        "canceled_at",
        "refunded_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentWebhookEvent)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = (
        "notification_id",
        "provider",
        "event_type",
        "resource_id",
        "signature_valid",
        "processing_status",
        "received_at",
    )

    list_filter = (
        "provider",
        "signature_valid",
        "processing_status",
        "received_at",
    )

    search_fields = (
        "notification_id",
        "resource_id",
        "request_id",
        "payment__external_reference",
        "payment__order__public_code",
    )

    ordering = (
        "-received_at",
    )

    readonly_fields = (
        "id",
        "payment",
        "provider",
        "notification_id",
        "event_type",
        "action",
        "resource_id",
        "request_id",
        "deduplication_key",
        "payload_sha256",
        "signature_valid",
        "processing_status",
        "processing_attempts",
        "failure_reason",
        "received_at",
        "processed_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False