from django.contrib import admin

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    show_change_link = True

    fields = (
        "ticket_type",
        "ticket_lot",
        "quantity",
        "unit_price",
        "subtotal",
        "created_at",
    )

    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "public_code",
        "buyer",
        "event",
        "organization",
        "status",
        "total",
        "reservation_expires_at",
        "created_at",
    )

    list_filter = (
        "status",
        "organization",
        "created_at",
    )

    search_fields = (
        "public_code",
        "buyer__email",
        "event__title",
        "organization__name",
    )

    list_select_related = (
        "buyer",
        "event",
        "organization",
    )

    readonly_fields = (
        "id",
        "public_code",
        "idempotency_key",
        "buyer",
        "organization",
        "event",
        "status",
        "subtotal",
        "service_fee",
        "total",
        "reservation_expires_at",
        "created_at",
        "updated_at",
    )

    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    inlines = (OrderItemInline,)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "ticket_type",
        "ticket_lot",
        "quantity",
        "unit_price",
        "subtotal",
        "created_at",
    )

    search_fields = (
        "order__public_code",
        "ticket_type__name",
        "ticket_lot__name",
    )

    list_select_related = (
        "order",
        "ticket_type",
        "ticket_lot",
    )

    readonly_fields = (
        "id",
        "order",
        "ticket_type",
        "ticket_lot",
        "quantity",
        "unit_price",
        "subtotal",
        "created_at",
        "updated_at",
    )

    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False