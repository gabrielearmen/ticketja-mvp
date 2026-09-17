from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


admin.site.site_header = "Administração TicketJá"
admin.site.site_title = "TicketJá"
admin.site.index_title = "Gestão da plataforma"


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("", include("apps.events.urls")),
    path("", include("apps.orders.urls")),
    path("", include("apps.organizations.urls")),
    path("", include("apps.core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )