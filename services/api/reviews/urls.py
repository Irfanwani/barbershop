"""``/api/v1/reviews/`` — ratings and comments."""

from django.urls import path

from reviews.views import (
    ReviewCreateView,
    ReviewDetailView,
    ReviewListView,
    ReviewReplyView,
)

app_name = "reviews"

urlpatterns = [
    path("", ReviewListView.as_view(), name="list"),
    path("new/", ReviewCreateView.as_view(), name="create"),
    path("<int:pk>/", ReviewDetailView.as_view(), name="detail"),
    path("<int:pk>/reply/", ReviewReplyView.as_view(), name="reply"),
]
