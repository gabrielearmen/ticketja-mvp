from django.contrib import admin

from .models import (
    Event,
    TicketLot,
    TicketType,
)


class TicketLotInline(admin.TabularInline):
    model = TicketLot
    extra = 0

    fields = (
        "name",
        "price",
        "quantity",
        "sales_start",
        "sales_end",
        "is_active",
    )

    show_change_link = True


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "organization",
        "sport_category",
        "event_datetime",
        "status",
    )

    list_filter = (
        "status",
        "sport_category",
        "state",
    )

    search_fields = (
        "title",
        "organization__name",
        "city",
    )

    autocomplete_fields = ("organization",)

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    list_select_related = ("organization",)
    ordering = ("event_datetime",)


@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "event",
        "capacity",
        "is_active",
    )

    list_filter = (
        "is_active",
        "event__organization",
    )

    search_fields = (
        "name",
        "event__title",
        "event__organization__name",
    )

    autocomplete_fields = ("event",)
    list_select_related = ("event",)
    inlines = (TicketLotInline,)

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )


@admin.register(TicketLot)
class TicketLotAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "ticket_type",
        "price",
        "quantity",
        "sales_start",
        "sales_end",
        "is_active",
    )

    list_filter = (
        "is_active",
        "ticket_type__event__organization",
    )

    search_fields = (
        "name",
        "ticket_type__name",
        "ticket_type__event__title",
    )

    autocomplete_fields = ("ticket_type",)
    list_select_related = (
        "ticket_type",
        "ticket_type__event",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )