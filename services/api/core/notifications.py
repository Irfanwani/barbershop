"""Outbound push notifications.

One place that knows how to talk to Expo, so a message sent from a view and a
message sent from a scheduled task cannot drift apart.

Every function here is safe to call when push is not configured. A deployment
without a push service loses reminders, not bookings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import requests
from django.conf import settings

if TYPE_CHECKING:
    from bookings.models import Booking

logger = logging.getLogger(__name__)

#: Expo's own limit. Sending more in one request is rejected outright, so a
#: large fan-out has to be chunked rather than retried.
MAX_TOKENS_PER_REQUEST = 100

REQUEST_TIMEOUT_SECONDS = 5


def deliver_push(
    tokens: list[str], *, title: str, body: str, data: dict[str, Any] | None = None
) -> bool:
    """Send one message to many devices.

    Returns whether it went out, but never raises: a push failure must not take
    down the request or the task that triggered it. Callers that need to know
    should read the logs.
    """
    tokens = [token for token in dict.fromkeys(tokens) if token]
    if not tokens:
        return False

    if not settings.PUSH_NOTIFICATION_URL:
        logger.debug("No PUSH_NOTIFICATION_URL configured; skipping push %r", title)
        return False

    sent_any = False
    for start in range(0, len(tokens), MAX_TOKENS_PER_REQUEST):
        chunk = tokens[start : start + MAX_TOKENS_PER_REQUEST]
        try:
            response = requests.post(
                settings.PUSH_NOTIFICATION_URL,
                json={"to": chunk, "title": title, "body": body, "data": data or {}},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            sent_any = True
        except Exception:
            # Log the tokens that failed so they can be deactivated by hand
            # rather than retried forever against a device that is gone.
            logger.exception("Could not deliver push %r to %d device(s)", title, len(chunk))
    return sent_any


def format_appointment_time(booking: Booking) -> str:
    """A time the recipient can read, in the shop's own timezone."""
    local = booking.provider.localtime(booking.starts_at)
    return local.strftime("%a %d %b, %I:%M %p")


def reminder_body(booking: Booking, *, audience: str) -> str:
    """The sentence a person actually reads.

    Different for each side: the customer wants to know where to go, the
    provider wants to know who is coming.
    """
    when = format_appointment_time(booking)
    if audience == "provider":
        return f"{booking.customer.get_full_name() or booking.customer.username} at {when}"
    return f"{booking.provider.display_name} at {when}"
