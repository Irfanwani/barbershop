"""Asking for the review.

Reviews are tied to completed bookings, so the trust signal is already right:
somebody can only review an appointment they actually had. What was missing is
anybody asking.

Three rules, each of which is a way this becomes spam:

- **Once per booking, ever.** A second nudge to the same person about the same
  haircut is the thing that gets notifications turned off entirely, which
  costs us the booking confirmations too.
- **A booking that is already reviewed is never nudged.** The alternative is
  reminding somebody to do a thing they have done.
- **Long enough afterwards to be useful.** Immediately after an appointment,
  nobody has an opinion yet; the reason to ask is that they will.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from core.notifications import deliver_push
from reviews.models import ReviewRequest

logger = logging.getLogger(__name__)

#: A day afterwards. Long enough to have an opinion, short enough that they
#: still remember whose chair it was.
NUDGE_AFTER_DAYS = 1

#: Past this the review is not worth asking for. Three months on, it is about
#: the platform, not the haircut.
NUDGE_UNTIL_DAYS = 30


@transaction.atomic
def request_review(booking: Booking) -> bool:
    """Record that we asked. Returns whether this was the first ask."""
    existing = ReviewRequest.objects.filter(booking=booking).first()
    if existing is not None:
        return False
    ReviewRequest.objects.create(booking=booking, customer=booking.customer)
    return True


def due(now: datetime | None = None) -> list[Booking]:
    """Bookings worth asking about, and not yet asked about."""
    from reviews.models import Review

    moment = now or timezone.now()
    oldest = moment - timedelta(days=NUDGE_UNTIL_DAYS)
    newest = moment - timedelta(days=NUDGE_AFTER_DAYS)

    asked = ReviewRequest.objects.values_list("booking_id", flat=True)

    return list(
        Booking.objects.filter(
            status=BookingStatus.COMPLETED,
            completed_at__isnull=False,
            # At least NUDGE_AFTER_DAYS ago, and not more than NUDGE_UNTIL_DAYS.
            completed_at__lte=newest,
            completed_at__gte=oldest,
        )
        # Already reviewed: asking again is asking for something they did.
        .exclude(pk__in=Review.objects.values_list("booking_id", flat=True))
        .exclude(pk__in=asked)
        .select_related("customer", "provider")
    )


def send_requests(now: datetime | None = None) -> dict[str, int]:
    """Ask, once each, for the reviews that are due.

    Read-only on the count of who is eligible; the ask itself is recorded
    separately so a failed push does not mean the person is never asked.
    """
    counts = {"eligible": 0, "sent": 0, "already_asked": 0, "opted_out": 0, "no_tokens": 0}

    moment = now or timezone.now()
    oldest = moment - timedelta(days=NUDGE_UNTIL_DAYS)
    newest = moment - timedelta(days=NUDGE_AFTER_DAYS)

    from reviews.models import Review, ReviewRequest

    already = set(ReviewRequest.objects.values_list("booking_id", flat=True))
    reviewed = set(Review.objects.values_list("booking_id", flat=True))

    candidates = Booking.objects.filter(
        status=BookingStatus.COMPLETED,
        completed_at__isnull=False,
        # At least a day ago — somebody has an opinion by now — and not more
        # than a month, past which the review stops being about the haircut.
        completed_at__lte=newest,
        completed_at__gte=oldest,
    ).select_related("customer", "provider")

    for booking in candidates:
        if booking.pk in already:
            counts["already_asked"] += 1
            continue
        if booking.pk in reviewed:
            continue

        counts["eligible"] += 1

        if not _wants(booking.customer):
            counts["opted_out"] += 1
            continue

        tokens = list(
            booking.customer.push_tokens.filter(active=True).values_list("token", flat=True)
        )
        if not tokens:
            counts["no_tokens"] += 1
            continue

        deliver_push(
            tokens,
            title="How did it go?",
            body=(
                f"You visited {booking.provider.display_name}. A review helps the "
                "next person decide."
            ),
            data={"screen": "review", "booking": booking.reference},
        )
        ReviewRequest.objects.create(booking=booking, customer=booking.customer)
        counts["sent"] += 1

    if counts["sent"]:
        logger.info("Review requests: %s", counts)
    return counts


def _wants(user: Any) -> bool:
    """Whether this account has agreed to hear about this.

    A review request is transactional - it is about an appointment that already
    happened - so it does not need an opt-in. It does follow one switch: the
    reminders opt-out, which is the category a person turns off when they want
    to stop being buzzed about their own appointments.

    The previous version required *every* category to be off at once. That could
    never be true: `bookingChanges` is required and the server forces it back
    on, so the condition was dead code and the opt-out it appeared to honour was
    never actually read by anybody. A preference check that cannot be false is
    worse than no check, because it looks like consent was respected.
    """
    from accounts.models import NotificationKey, wants_notification

    return wants_notification(user, NotificationKey.BOOKING_REMINDERS) is not False


def notify_provider(review) -> bool:
    """Tell the shop a review arrived. Reviews arrive unprompted often enough."""
    tokens = list(
        review.provider.user.push_tokens.filter(active=True).values_list("token", flat=True)
    )
    if not tokens:
        return False

    deliver_push(
        tokens,
        title="New review",
        body=f"{review.rating}★ from a customer of {review.provider.display_name}.",
        data={"screen": "reviews", "review_id": review.pk},
    )
    return True
