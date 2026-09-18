from django.contrib import admin

from .models import Registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order_code",
        "position",
        "full_name",
        "document_type",
        "completed_at",
    )

    list_filter = (
        "document_type",
        "completed_at",
    )

    search_fields = (
        "full_name",
        "document_number",
        "order_item__order__public_code",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "order_item",
        "order_item__order",
    )

    def order_code(self, registration):
        return registration.order_item.order.public_code

    order_code.short_description = "Pedido"

    def has_add_permission(self, request):
        # Inscrições devem ser criadas pelo serviço transacional,
        # nunca manualmente pelo administrador.
        return False

    def has_delete_permission(self, request, obj=None):
        # Preserva o histórico operacional e financeiro.
        return False