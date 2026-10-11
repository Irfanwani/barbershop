"""URL configuration for API version 1.

Everything the mobile client talks to lives under this prefix. When v2 arrives it
gets its own module and is mounted beside this one — v1 keeps serving until the
app has migrated off it.
"""

from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    # --- auth ----------------------------------------------------------------
    path("auth/", include("accounts.urls_auth")),
    path("me/", include("accounts.urls_me")),
    # --- providers -----------------------------------------------------------
    path("providers/", include("providers.urls")),
    # --- bookings -----------------------------------------------------------
    path("bookings/", include("bookings.urls")),
    # --- reviews -----------------------------------------------------------
    path("reviews/", include("reviews.urls")),
    # --- payments ----------------------------------------------------------
    path("payments/", include("payments.urls")),
    # --- catalogue ----------------------------------------------------------
    path("products/", include("catalog.urls")),
    # --- docs ----------------------------------------------------------------
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="v1:schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="v1:schema"), name="redoc"),
]
