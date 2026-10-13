"""``/api/v1/api-keys/`` — managing your own keys."""

from django.urls import path

from api_keys.views import (
    ApiKeyUsageView,
    MyApiKeyDetailView,
    MyApiKeysView,
)

app_name = "api_keys"

urlpatterns = [
    path("", MyApiKeysView.as_view(), name="list"),
    path("usage/", ApiKeyUsageView.as_view(), name="usage"),
    path("<int:pk>/", MyApiKeyDetailView.as_view(), name="detail"),
]
