"""Root URL configuration.

The admin and a health check live at the root; the API itself is mounted from a
separate module so it can be versioned without touching anything else here.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthcheck(_request):
    """Cheap liveness probe. Deliberately does not touch the database."""
    return JsonResponse({"status": "ok", "service": "barbershop-api"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("config.api")),
    path("healthz", healthcheck, name="healthcheck"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "BarberShop administration"
admin.site.site_title = "BarberShop admin"
admin.site.index_title = "Operations"
