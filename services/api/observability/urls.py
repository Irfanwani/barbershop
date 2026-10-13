"""``/api/v1/observability/`` — metrics and delivery failures."""

from django.urls import path

from observability.views import MetricsView, RecordDeliveryFailureView

app_name = "observability"

urlpatterns = [
    path("metrics/", MetricsView.as_view(), name="metrics"),
    path("delivery-failure/", RecordDeliveryFailureView.as_view(), name="delivery-failure"),
]
