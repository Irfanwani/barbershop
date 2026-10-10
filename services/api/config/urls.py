"""Root URL configuration.

``/api/v1/`` is the supported surface. The two ``/api/`` mounts below are the
pre-v1 handlers, kept only until the bookings/payments endpoints land in v1 and
the data migrations retire their tables.
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
    # --- deprecated, unversioned, removed in the next commit ----------------
    path("api/haircut/", include("haircut.urls")),
    path("api/payments/", include("payments.urls")),
    path("healthz", healthcheck, name="healthcheck"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "BarberShop administration"
admin.site.site_title = "BarberShop admin"
admin.site.index_title = "Operations"
