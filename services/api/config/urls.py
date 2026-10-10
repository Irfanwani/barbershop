"""Root URL configuration.

``/api/v1/`` is the only supported surface. The pre-v1, unversioned handlers
were removed once their data had been migrated across.
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
    path("api/v1/", include(("config.api", "v1"), namespace="v1")),
    path("healthz", healthcheck, name="healthcheck"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "BarberShop administration"
admin.site.site_title = "BarberShop admin"
admin.site.index_title = "Operations"
