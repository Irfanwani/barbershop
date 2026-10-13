"""Celery application.

Everything scheduled — booking reminders, expiring appointments, expiring push
tokens — runs here rather than in a request. A user closing the app must not
stop a reminder going out, and a slow reminder must not hold an HTTP response
open.
"""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("barbershop")

app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # Booking reminders go out in the morning for appointments later that day,
    # and the evening before for tomorrow. A provider working a chair at 09:00
    # needs to know about the 10:00 slot now, not at 09:55.
    "booking-reminders-morning": {
        "task": "bookings.reminders.send_daily_reminders",
        "schedule": crontab(hour=8, minute=0),
    },
    "booking-reminders-evening": {
        "task": "bookings.reminders.send_evening_reminders",
        "schedule": crontab(hour=18, minute=0),
    },
    # An appointment nobody turned up for is still marked "confirmed" forever
    # without this, which then blocks the slot for good.
    "expire-stale-bookings": {
        "task": "bookings.reminders.expire_stale_bookings",
        "schedule": crontab(minute="*/15"),
    },
    # A slot held for someone who never answered goes back to the public list.
    # Frequent, because every one of those is an empty chair in a shop that is
    # open.
    "expire-waitlist-offers": {
        "task": "bookings.waitlist.expire_offers",
        "schedule": crontab(minute="*/5"),
    },
    # Is anybody still being reminded of their appointment?
    #
    # Hourly, because the failure this exists to catch is the one that does not
    # announce itself: the reminder job runs, sends nothing, and reports success.
    # Nothing crashes, every dashboard is green, and nobody is told.
    "check-delivery-health": {
        "task": "observability.tasks.check_delivery_health",
        "schedule": crontab(minute="*/15"),
    },
    # Cheapest revenue on the platform: the customer already liked the haircut.
    # Daily, because the window is measured in weeks and the record of who has
    # been told means a missed run is not a missed customer forever.
    "rebooking-nudges": {
        "task": "bookings.reminders.send_rebooking_nudges",
        "schedule": crontab(hour=11, minute=30),
    },
    # Reviews are already tied to completed bookings, so the trust signal is
    # right. Nobody was asking, which is the other half of it.
    "review-requests": {
        "task": "bookings.reminders.request_reviews",
        "schedule": crontab(hour=16, minute=0),
    },
    # The next visit of every running series. Daily, and only ever one
    # occurrence per series per run, so a task that was down for a week does not
    # arrive and book seven appointments in one go.
    "materialise-recurring-series": {
        "task": "bookings.tasks.materialise_recurring_series",
        "schedule": crontab(hour=4, minute=15),
    },
    # A WhatsApp provider that timed out leaves the message unsent and the
    # customer unconfirmed. Every five minutes, because a missed confirmation
    # is a missed appointment.
    "retry-stuck-whatsapp": {
        "task": "bookings.tasks.retry_stuck_whatsapp_messages",
        "schedule": crontab(minute="*/5"),
    },
    # The score is also computed on demand at quote time, so this only keeps
    # the stored copy roughly current. Flags are raised, never acted on
    # automatically - a human decides what a flag means.
    "risk-refresh": {
        "task": "risk.tasks.refresh_risk_profiles",
        "schedule": crontab(hour=5, minute=10),
    },
    "risk-sweep": {
        "task": "risk.tasks.sweep_risk_flags",
        "schedule": crontab(hour=5, minute=25),
    },
    "expire-stale-push-tokens": {
        "task": "accounts.tasks.expire_stale_tokens",
        "schedule": crontab(hour=3, minute=0),
    },
    "prune-spent-codes": {
        "task": "accounts.tasks.prune_used_verification_codes",
        "schedule": crontab(hour=3, minute=30),
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> str:  # pragma: no cover - operational helper
    """Print the request, to confirm a worker is alive and wired up."""
    return f"request: {self.request!r}"
