"""``/api/v1/bookings/`` — appointments between a customer and a provider."""

from django.urls import path

from bookings.views import (
    BookingCancelView,
    BookingCollectView,
    BookingCreateView,
    BookingDetailView,
    BookingListView,
    BookingRescheduleView,
    BookingStatusView,
    ConsultationFormsView,
    QuoteView,
    WaitlistEntryDetailView,
    WaitlistOfferAcceptView,
    WaitlistOfferDeclineView,
    WaitlistOfferListView,
    WaitlistView,
)

app_name = "bookings"

urlpatterns = [
    path("", BookingListView.as_view(), name="list"),
    path("quote/", QuoteView.as_view(), name="quote"),
    path("consultation-forms/", ConsultationFormsView.as_view(), name="consultation-forms"),
    path("waitlist/", WaitlistView.as_view(), name="waitlist"),
    path("waitlist/offers/", WaitlistOfferListView.as_view(), name="waitlist-offers"),
    path(
        "waitlist/offers/<int:pk>/accept/",
        WaitlistOfferAcceptView.as_view(),
        name="waitlist-offer-accept",
    ),
    path(
        "waitlist/offers/<int:pk>/decline/",
        WaitlistOfferDeclineView.as_view(),
        name="waitlist-offer-decline",
    ),
    path("waitlist/<int:pk>/", WaitlistEntryDetailView.as_view(), name="waitlist-detail"),
    path("new/", BookingCreateView.as_view(), name="create"),
    path("<str:reference>/", BookingDetailView.as_view(), name="detail"),
    path("<str:reference>/cancel/", BookingCancelView.as_view(), name="cancel"),
    path(
        "<str:reference>/reschedule/",
        BookingRescheduleView.as_view(),
        name="reschedule",
    ),
    path("<str:reference>/collect/", BookingCollectView.as_view(), name="collect"),
    path(
        "<str:reference>/<str:action>/",
        BookingStatusView.as_view(),
        name="status",
    ),
]
