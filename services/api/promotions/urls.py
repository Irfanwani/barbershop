"""``/api/v1/promotions/`` — points and codes."""

from django.urls import path

from promotions.views import (
    BookingPointsView,
    MyReferralsView,
    PointsBalanceView,
    PointsHistoryView,
    PointsSettingsView,
    ProviderReferralStatsView,
)

app_name = "promotions"

urlpatterns = [
    path("points/", PointsBalanceView.as_view(), name="points"),
    path("points/history/", PointsHistoryView.as_view(), name="points-history"),
    path("points/settings/", PointsSettingsView.as_view(), name="points-settings"),
    path("bookings/<str:reference>/points/", BookingPointsView.as_view(), name="booking-points"),
    path("referrals/me/", MyReferralsView.as_view(), name="my-referrals"),
    path("referrals/provider/", ProviderReferralStatsView.as_view(), name="provider-referrals"),
]
