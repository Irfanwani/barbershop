"""Scheduled booking work: reminders and expiry.

Two jobs that were previously nobody's:

* **Reminders.** The customer and the provider each get told about an
  appointment before it happens. Without this a no-show is a coin flip.
* **Expiry.** An appointment nobody cancelled or turned up for sat at
  ``confirmed`` forever, and because that status blocks its slot, the provider
  could never book that time again.

Reminders honour the user's notification preferences, which live on the account
rather than the device: a user who switches reminders off on one phone should
stop getting them on all of them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from core.notifications import deliver_push, format_appointment_time

logger = logging.getLogger(__name__)

#: How long after the end of an appointment it is treated as expired. A little
#: grace, so a booking that runs slightly over is not written off while the
#: provider is still finishing the last cut.
EXPIRY_GRACE = timedelta(hours=2)

#: Reminder lead times in hours before the appointment starts.
MORNING_LEAD_HOURS = 3
EVENING_LEAD_HOURS = 14  # The evening before.


def _reminders_due(now: datetime, lead_hours: int) -> list[Booking]:
    """Confirmed appointments entering their reminder window, not yet reminded.

    Only appointments that are actually going ahead. Reminding someone about a
    request the provider has not accepted yet is worse than saying nothing.
    """
    window_start = now + timedelta(hours=lead_hours - 1)
    window_end = now + timedelta(hours=lead_hours)

    return list(
        Booking.objects.filter(
            status=BookingStatus.CONFIRMED,
            starts_at__gte=window_start,
            starts_at__lt=window_end,
            reminder_sent_at__isnull=True,
        ).select_related("customer", "provider")
    )


def _wants_reminders(user) -> bool:
    """Whether this account still wants appointment reminders."""
    profile = getattr(user, "customer_profile", None) or getattr(user, "provider_profile", None)
    if profile is None:
        # No profile is not consent to be ignored: default to sending.
        return True
    return bool(getattr(profile, "reminders_enabled", True))


def _send_reminders(bookings: list[Booking], *, audience: str) -> int:
    """Send reminders to one side. Returns how many messages went out."""
    sent = 0
    now = timezone.now()

    for booking in bookings:
        user = booking.customer if audience == "customer" else booking.provider.user
        tokens = list(user.push_tokens.filter(active=True).values_list("token", flat=True))

        if tokens and _wants_reminders(user):
            deliver_push(
                tokens,
                title="Appointment reminder",
                body=_body(booking, audience=audience),
                data={"screen": "/bookings", "reference": booking.reference},
            )
            sent += 1
        elif not tokens:
            logger.debug("No push token for %s; skipping reminder", user.username)

        # Marked sent either way. A user with no token, or who has switched
        # reminders off, must not be picked up again on the next run.
        Booking.objects.filter(pk=booking.pk).update(reminder_sent_at=now)

    return sent


def _body(booking: Booking, *, audience: str) -> str:
    when = format_appointment_time(booking)
    if audience == "provider":
        name = booking.customer.get_full_name() or booking.customer.username
        return f"{name} at {when} · {booking.reference}"
    return f"{booking.provider.display_name} at {when} · {booking.reference}"


@shared_task(name="bookings.reminders.send_daily_reminders")
def send_daily_reminders() -> dict[str, int]:
    """Remind both sides about appointments starting later today."""
    bookings = _reminders_due(timezone.now(), MORNING_LEAD_HOURS)
    return {
        "customer": _send_reminders(bookings, audience="customer"),
        "provider": _send_reminders(bookings, audience="provider"),
    }


@shared_task(name="bookings.reminders.send_evening_reminders")
def send_evening_reminders() -> dict[str, int]:
    """Remind both sides about tomorrow's appointments, the evening before."""
    bookings = _reminders_due(timezone.now(), EVENING_LEAD_HOURS)
    return {
        "customer": _send_reminders(bookings, audience="customer"),
        "provider": _send_reminders(bookings, audience="provider"),
    }


@shared_task(name="bookings.reminders.expire_stale_bookings")
def expire_stale_bookings() -> dict[str, int]:
    """Close out appointments that ended without anyone marking them finished.

    Runs every fifteen minutes, so a provider opening the app in the evening
    sees the day as history rather than as still ahead.
    """
    now = timezone.now()
    counts: dict[str, int] = {}

    with transaction.atomic():
        # Confirmed and past its end: nobody turned up, or nobody said so.
        counts["no_show"] = _expire(
            Booking.objects.filter(status=BookingStatus.CONFIRMED, ends_at__lt=now - EXPIRY_GRACE),
            BookingStatus.NO_SHOW,
        )

        # Never paid for. The customer is not at fault and no money moved, so
        # this is `expired` rather than any kind of cancellation.
        counts["unpaid"] = _expire(
            Booking.objects.filter(status=BookingStatus.PENDING_PAYMENT, starts_at__lt=now),
            BookingStatus.EXPIRED,
        )

        # Asked for, never accepted, and the slot has passed. Also expired: the
        # provider never agreed to it, so blaming either side would be wrong.
        counts["unanswered"] = _expire(
            Booking.objects.filter(status=BookingStatus.AWAITING_CONFIRMATION, starts_at__lt=now),
            BookingStatus.EXPIRED,
        )

    if any(counts.values()):
        logger.info("Expired bookings: %s", counts)
    return counts


def _expire(queryset, new_status: BookingStatus) -> int:
    ids = list(queryset.values_list("pk", flat=True))
    if not ids:
        return 0
    queryset.update(status=new_status, expired_at=timezone.now())
    return len(ids)
