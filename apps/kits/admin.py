from django.contrib import admin

from .models import (
    EventKit,
    KitOption,
    TicketTypeKit,
)


class KitOptionInline(admin.TabularInline):
    model = KitOption
    extra = 0

    fields = (
        "name",
        "stock_quantity",
        "is_active",
    )

    def has_delete_permission(self, request, obj=None):
        return False


class TicketTypeKitInline(admin.TabularInline):
    model = TicketTypeKit
    extra = 0

    fields = (
        "ticket_type",
    )

    autocomplete_fields = (
        "ticket_type",
    )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EventKit)
class EventKitAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "event",
        "is_required",
        "is_active",
        "updated_at",
    )

    list_filter = (
        "is_required",
        "is_active",
    )

    search_fields = (
        "name",
        "event__title",
        "event__organization__name",
    )

    list_select_related = (
        "event",
        "event__organization",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    inlines = (
        KitOptionInline,
        TicketTypeKitInline,
    )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(KitOption)
class KitOptionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "kit",
        "stock_quantity",
        "is_active",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "name",
        "kit__name",
        "kit__event__title",
    )

    list_select_related = (
        "kit",
        "kit__event",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TicketTypeKit)
class TicketTypeKitAdmin(admin.ModelAdmin):
    list_display = (
        "kit",
        "ticket_type",
        "created_at",
    )

    search_fields = (
        "kit__name",
        "ticket_type__name",
        "ticket_type__event__title",
    )

    list_select_related = (
        "kit",
        "kit__event",
        "ticket_type",
    )

    readonly_fields = (
        "id",
        "created_at",
    )

    def has_delete_permission(self, request, obj=None):
        return False