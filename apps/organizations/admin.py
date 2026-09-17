from django.contrib import admin

from .models import Organization, OrganizationMembership


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "status",
        "created_at",
    )

    list_filter = ("status",)

    search_fields = (
        "name",
        "slug",
    )

    prepopulated_fields = {
        "slug": ("name",),
    }

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "organization",
        "role",
        "is_active",
    )

    list_filter = (
        "role",
        "is_active",
        "organization__status",
    )

    search_fields = (
        "user__email",
        "organization__name",
    )

    autocomplete_fields = (
        "user",
        "organization",
    )