"""``/api/v1/providers/`` — discovery, service menu, payouts and availability."""

from django.urls import path

from providers.views import (
    AvailabilityView,
    BookingToggleView,
    MyPayoutView,
    MyProviderView,
    MyServiceDetailView,
    MyServiceView,
    MyWorkingHoursView,
    PriceInsightView,
    ProviderDetailView,
    ProviderListView,
    ServicePriceIndexView,
    ServiceTypeListView,
)

app_name = "providers"

urlpatterns = [
    path("", ProviderListView.as_view(), name="list"),
    path("types/", ServiceTypeListView.as_view(), name="types"),
    path("prices/", PriceInsightView.as_view(), name="prices"),
    path("prices/services/", ServicePriceIndexView.as_view(), name="service-prices"),
    path("me/", MyProviderView.as_view(), name="me"),
    path("me/services/", MyServiceView.as_view(), name="my-services"),
    path("me/services/<int:pk>/", MyServiceDetailView.as_view(), name="my-service-detail"),
    path("me/payout/", MyPayoutView.as_view(), name="my-payout"),
    path("me/hours/", MyWorkingHoursView.as_view(), name="my-hours"),
    path("me/accepting-bookings/", BookingToggleView.as_view(), name="my-accepting-bookings"),
    path("<int:pk>/", ProviderDetailView.as_view(), name="detail"),
    path("<int:pk>/availability/", AvailabilityView.as_view(), name="availability"),
]
