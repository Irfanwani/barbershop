"""API URLs.

Currently this is the legacy, unversioned surface carried over from
``barbershopbackend``. It is being replaced by ``/api/v1/``.
"""

from django.urls import include, path

urlpatterns = [
    path("accounts/", include("accounts.urls")),
    path("haircut/", include("haircut.urls")),
    path("payments/", include("payments.urls")),
]
