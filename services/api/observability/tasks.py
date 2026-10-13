"""Scheduled checks.

Hourly, because the thing being watched is whether reminders are *arriving*, and
an hourly check on an hourly job is exactly the resolution at which a failure
first becomes visible.
"""

from __future__ import annotations

import logging

from celery import shared_task

from observability import alerts

logger = logging.getLogger("observability.tasks")


@shared_task(ignore_result=True)
def check_delivery_health() -> None:
    """Raise one alert if reminders have stopped arriving.

    The failure this exists for is the one that does not announce itself: the
    job runs, sends nothing, and reports success.
    """
    alerts.check_reminder_delivery()
