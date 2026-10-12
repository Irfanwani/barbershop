"""``/api/v1/promotions/`` — points and codes."""

from django.urls import path

from promotions.views import (
    BookingPointsView,
    PointsBalanceView,
    PointsHistoryView,
    PointsSettingsView,
)

app_name = "promotions"

urlpatterns = [
    path("points/", PointsBalanceView.as_view(), name="points"),
    path("points/history/", PointsHistoryView.as_view(), name="points-history"),
    path("points/settings/", PointsSettingsView.as_view(), name="points-settings"),
    path("bookings/<str:reference>/points/", BookingPointsView.as_view(), name="booking-points"),
]
