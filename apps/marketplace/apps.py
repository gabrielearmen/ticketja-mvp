from django.apps import AppConfig


class MarketplaceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.marketplace"
    verbose_name = "Marketplace e recebimentos"

    def ready(self):
        # Registra verificações de configuração sem executar chamadas
        # externas durante a inicialização do Django.
        from . import checks  # noqa: F401
