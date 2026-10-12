"""Finding the customers who liked the haircut and quietly stopped.

"Most salon owners have no idea how many clients rebook within 6 to 8 weeks."
Neither did we. It is the cheapest revenue on the platform, because the work
is already done — somebody liked this shop enough to sit in the chair once.

Three things make this something other than a marketing blast:

- **Once per customer per shop, ever.** A nudge says "we noticed you have not
  been back", not "we would like to tell you about something". Somebody who
  ignored three of them is not interested in a fourth.
- **It respects the same preferences as everything else.** Off means off, read
  from the same place the settings screen writes.
- **The message is a link to the shop, not an offer.** The customer already
  knows this shop. What they have forgotten is that it exists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Max
from django.utils import timezone

from accounts.models import NotificationKey, RebookingNudge, wants_notification
from bookings.models import Booking, BookingStatus
from core.notifications import deliver_push

logger = logging.getLogger(__name__)

#: The window. A cut every fortnight is a regular; one every two months is
#: lapsed. Nudging sooner is nudging somebody mid-routine, which is how a
#: "come back" message turns into a muted category.
LAPSED_AFTER_DAYS = 35
NUDGE_AFTER_DAYS = 56

#: Past this they are not lapsed, they are gone. Pulling somebody back after
#: six months is unsettling rather than helpful.
NURTURE_UNTIL_DAYS = 180


@dataclass(frozen=True)
class LapsedCustomer:
    customer: Any
    provider: Any
    last_booking: Booking

    @property
    def pair(self) -> tuple[int, int]:
        return (self.customer.pk, self.provider.pk)


def shop_url(provider: Any) -> str:
    """The shop's own public page.

    A web link rather than a deep link: the customer may not have the app
    installed, and for this particular message a page that shows the price
    beats a dead end.
    """
    from providers.public import site_url

    return f"{site_url()}/shops/{provider.slug}/"


def lapsed_customers(
    *,
    now: datetime | None = None,
    lapsed_after_days: int = LAPSED_AFTER_DAYS,
    nudge_after_days: int = NUDGE_AFTER_DAYS,
    until_days: int = NURTURE_UNTIL_DAYS,
) -> list[LapsedCustomer]:
    """Everyone whose last completed booking was long enough ago.

    Grouped per *customer*, not per shop. The question is "has this person
    stopped coming back", not "has this person stopped coming back to that
    shop" — somebody who moved to a competitor three shops over is not ours to
    nudge back into this one, and telling them about a shop they have moved on
    from is the single fastest way to get a notification muted.
    """
    moment = now or timezone.now()
    oldest = moment - timedelta(days=until_days)
    newest_lapsed = moment - timedelta(days=nudge_after_days)

    completed = Booking.objects.filter(
        status=BookingStatus.COMPLETED,
        ends_at__gte=oldest,
        ends_at__lte=most_recent_boundary(moment, lapsed_after_days),
    )

    # Their most recent completed booking, one row per person.
    latest_at = dict(
        completed.values("customer_id")
        .annotate(last=Max("ends_at"))
        .values_list("customer_id", "last")
    )

    candidates: list[LapsedCustomer] = []
    for customer_id, last in latest_at.items():
        if last > newest_lapsed:
            continue
        booking = completed.filter(customer_id=customer_id, ends_at=last).first()
        if booking is None:
            continue
        candidates.append(
            LapsedCustomer(
                customer=booking.customer, provider=booking.provider, last_booking=booking
            )
        )
    return candidates


def most_recent_boundary(moment: datetime, lapsed_after_days: int) -> datetime:
    return moment - timedelta(days=lapsed_after_days)


def wants_nudge(user: Any) -> bool:
    """Whether this account has agreed to hear about this.

    Read from the same place the settings screen writes, so the two cannot
    disagree — which was the whole bug behind P3.5. Reminders count as consent:
    somebody who wants to hear from their barber at all has not opted out of
    being reminded.
    """
    return wants_notification(user, NotificationKey.OFFERS_AND_PROMOTIONS) or (
        wants_notification(user, NotificationKey.BOOKING_REMINDERS)
    )


def send_nudges(*, now: datetime | None = None, dry_run: bool = False) -> dict[str, int]:
    """Nudge each lapsed customer once, and only once.

    Returns counts rather than sending silently, so the task's log can say what
    it did and a test can assert on it.
    """
    counts = {"eligible": 0, "sent": 0, "already_nudged": 0, "opted_out": 0, "no_tokens": 0}

    already = set(RebookingNudge.objects.values_list("customer_id", "provider_id"))

    for candidate in lapsed_customers(now=now):
        if candidate.pair in already:
            counts["already_nudged"] += 1
            continue

        counts["eligible"] += 1

        if not wants_nudge(candidate.customer):
            counts["opted_out"] += 1
            continue

        tokens = list(
            candidate.customer.push_tokens.filter(active=True).values_list("token", flat=True)
        )
        if not tokens:
            counts["no_tokens"] += 1
            continue

        if not dry_run:
            deliver_push(
                tokens,
                title="Your barber is still there",
                body=(
                    f"You last visited {candidate.provider.display_name} a while ago. Book again?"
                ),
                data={
                    "screen": "shop",
                    "provider_id": candidate.provider.pk,
                    "url": shop_url(candidate.provider),
                },
            )
            RebookingNudge.objects.create(
                customer=candidate.customer,
                provider=candidate.provider,
                last_booking=candidate.last_booking,
            )

        counts["sent"] += 1

    if counts["sent"]:
        logger.info("Rebooking nudges: %s", counts)
    return counts
