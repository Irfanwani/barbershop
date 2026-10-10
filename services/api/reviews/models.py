"""Ratings and comments left after an appointment.

The old ``RatingsAndReviews`` accepted any positive integer as a rating, from any
authenticated user, about any barber, with no way to tie a review to a visit.
This one enforces both a range and a relationship.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TimeStampedModel
from providers.models import ProviderProfile

MIN_RATING = 1
MAX_RATING = 5


class Review(TimeStampedModel):
    """A customer's rating of a provider.

    ``booking`` is optional but, when given, must belong to the same customer and
    provider and must be finished. Linking a review to a completed booking is what
    makes "verified customer" mean anything.
    """

    provider = models.ForeignKey(ProviderProfile, on_delete=models.CASCADE, related_name="reviews")
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews",
        limit_choices_to={"role": "customer"},
    )

    booking = models.OneToOneField(
        "bookings.Booking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review",
        help_text="Set when the review follows a completed booking.",
    )

    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(MIN_RATING), MaxValueValidator(MAX_RATING)]
    )
    comment = models.TextField(blank=True, default="", max_length=1000)

    provider_reply = models.TextField(blank=True, default="", max_length=1000)
    replied_at = models.DateTimeField(null=True, blank=True)

    is_hidden = models.BooleanField(
        default=False, help_text="Hidden by moderation. Kept, not deleted."
    )

    class Meta:
        db_table = "reviews_review"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "-created_at"]),
            models.Index(fields=["customer", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=MIN_RATING, rating__lte=MAX_RATING),
                name="reviews_rating_between_1_and_5",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rating}★ from {self.customer} for {self.provider}"
