"""``/api/v1/exports/`` — spreadsheets, by email."""

from django.urls import path

from exports.views import ExportRequestDetailView, ExportRequestView

app_name = "exports"

urlpatterns = [
    path("", ExportRequestView.as_view(), name="request"),
    path("<int:pk>/", ExportRequestDetailView.as_view(), name="detail"),
]
