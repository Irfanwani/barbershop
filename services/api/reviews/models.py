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

    photo = models.ImageField(
        upload_to="reviews/",
        blank=True,
        null=True,
        help_text="Optional. A picture of the result, which is what makes a review useful.",
    )

    is_hidden = models.BooleanField(
        default=False, help_text="Hidden by moderation. Kept, not deleted."
    )

    #: Why a provider asked for this to come down.
    #:
    #: Set only for abuse — harassment, spam, a review about somebody else.
    #: Being rated badly is not a reason, and a provider who can wave a review
    #: away by asking has no reason to keep the shop's rating honest.
    removal_requested_reason = models.CharField(max_length=200, blank=True, default="")
    removal_requested_at = models.DateTimeField(null=True, blank=True)

    @property
    def can_be_requested_removed(self) -> bool:
        """Whether a provider may ask for this review to come down."""
        return can_be_requested_removed(self.removal_requested_reason)

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


class ReviewRequest(TimeStampedModel):
    """That we asked this person to review this appointment.

    Recorded rather than inferred. "Have we asked?" cannot be derived from
    booking dates: a customer who reviews, and one who never will, look
    identical from the appointment's side, and a second nudge to somebody who
    has already declined is how a whole notification category gets turned off.
    """

    booking = models.OneToOneField(
        "bookings.Booking", on_delete=models.CASCADE, related_name="review_request"
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="review_requests"
    )

    class Meta:
        db_table = "reviews_reviewrequest"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"asked {self.customer} about {self.booking_id}"


#: What counts as a reason to take a review down. Abuse only.
#:
#: A provider who could wave away a review by asking would have no reason to
#: keep the shop's rating honest, and "we did not like it" is not abuse.
REMOVAL_REASONS = ("abuse", "harass", "spam", "threaten")


def can_be_requested_removed(reason: str) -> bool:
    """Whether this stated reason is one we will act on.

    A module function rather than a method, because the view has to check the
    reason it was *given*, not the one on the row — which is empty the first
    time and set afterwards, so checking the stored value refuses the first
    report and allows every later one.
    """
    cleaned = (reason or "").strip().lower()
    return bool(cleaned) and any(word in cleaned for word in REMOVAL_REASONS)
