"""``/api/v1/bookings/`` — appointments between a customer and a provider."""

from django.urls import path

from bookings.views import (
    BookingCancelView,
    BookingCollectView,
    BookingCreateView,
    BookingDetailView,
    BookingListView,
    BookingStatusView,
    QuoteView,
)

app_name = "bookings"

urlpatterns = [
    path("", BookingListView.as_view(), name="list"),
    path("quote/", QuoteView.as_view(), name="quote"),
    path("new/", BookingCreateView.as_view(), name="create"),
    path("<str:reference>/", BookingDetailView.as_view(), name="detail"),
    path("<str:reference>/cancel/", BookingCancelView.as_view(), name="cancel"),
    path("<str:reference>/collect/", BookingCollectView.as_view(), name="collect"),
    path(
        "<str:reference>/<str:action>/",
        BookingStatusView.as_view(),
        name="status",
    ),
]
