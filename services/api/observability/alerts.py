"""Alerts for the failure that does not announce itself.

A Celery job that crashes is loud: it logs, it retries, somebody sees. The
dangerous failure is the one that *succeeds* — a reminder that runs, finds no
deliverable tokens, and sends nothing, while every dashboard says the job is
green. Nobody is paged and nobody is told.

So the check is about the ratio of deliveries that worked, and it only fires
once the volume is big enough for the ratio to mean something. A 100% failure
rate across three reminders is three reminders, not an outage.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from observability.models import Alert, DeliveryFailure

logger = logging.getLogger("observability.alerts")

#: Below this many delivery attempts the ratio is noise, and paging on noise is
#: how a real alert gets ignored.
MIN_ATTEMPTS = 20

#: One in five is not a bad afternoon.
FAILURE_RATE_THRESHOLD = 0.2


def check_reminder_delivery(*, window_hours: int = 24) -> Alert | None:
    """Raise one alert if reminder delivery has stopped working.

    Returns the alert, or ``None`` when there is nothing to say. Idempotent: a
    live alert for this kind is left alone rather than paged again.
    """
    from observability import metrics

    outcomes: dict[str, int] = {}
    for key, value in metrics.snapshot()["counters"].items():
        if not key.startswith("reminder_delivery{"):
            continue
        for part in key[1:-1].split(","):
            if part.startswith("outcome="):
                outcomes[part.split("=", 1)[1]] = value

    sent = outcomes.get("sent", 0)
    failed = outcomes.get("failed", 0)
    attempts = sent + failed

    if attempts < MIN_ATTEMPTS:
        logger.info("Reminder delivery: %s attempts, not enough to judge", attempts)
        return None

    rate = failed / attempts
    if rate < FAILURE_RATE_THRESHOLD:
        _resolve_if_live("Reminder delivery recovered", details={"failure_rate": round(rate, 3)})
        return None

    existing = Alert.objects.filter(
        kind=Alert.Kind.REMINDER_DELIVERY, resolved_at__isnull=True
    ).first()
    if existing is not None:
        # Still failing, still alerted. Paging again every five minutes teaches
        # people to ignore the pager.
        logger.warning("Reminder delivery still failing (%.0f%%)", rate * 100)
        return existing

    alert = Alert.objects.create(
        kind=Alert.Kind.REMINDER_DELIVERY,
        severity="high",
        message=(f"{failed} of {attempts} reminders failed to deliver in the last {window_hours}h"),
        details={
            "sent": sent,
            "failed": failed,
            "failure_rate": round(rate, 3),
            "window_hours": window_hours,
            "recorded_failures": DeliveryFailure.objects.filter(
                created_at__gte=timezone.now() - timedelta(hours=window_hours)
            ).count(),
        },
    )
    logger.error("Reminder delivery failing: %s", alert.message)
    return alert


def _resolve_if_live(message: str, *, details: dict) -> None:
    """Close an alert that is no longer true.

    An alert that never clears is how a dashboard ends up permanently red and
    therefore permanently ignored.
    """
    live = Alert.objects.filter(kind=Alert.Kind.REMINDER_DELIVERY, resolved_at__isnull=True).first()
    if live is None:
        return
    live.resolved_at = timezone.now()
    live.message = message
    live.details = details
    live.save(update_fields=["resolved_at", "message", "details"])
    logger.info("Reminder delivery alert resolved")
