"""Transactional email.

Kept in one module because every message the platform sends has to answer the
same two questions: what is the code, and how long is it good for. Getting
those out of sync between the verification and password-reset flows is how people
end up pasting a signup code into the reset box.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

BRAND = "BarberShop"


def _send(subject: str, template: str, context: dict) -> bool:
    """Send one templated message.

    Returns whether it went out. A failure is logged and swallowed: an SMTP
    outage should produce a clear "we could not email you" response, not a 500
    that looks like the registration itself broke.
    """
    context.setdefault("brand", BRAND)
    context.setdefault("support_email", settings.DEFAULT_FROM_EMAIL)

    try:
        body = render_to_string(f"email/{template}.txt", context)
        message = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[context["to"]],
        )
        message.send(fail_silently=False)
    except Exception:
        logger.exception("Could not send %r to %s", subject, context.get("to"))
        return False
    return True


def send_verification_code(to: str, code: str, username: str) -> bool:
    return _send(
        subject=f"Confirm your {BRAND} email address",
        template="verification",
        context={
            "to": to,
            "code": code,
            "username": username,
            "ttl_hours": 24,
        },
    )


def send_password_reset_code(to: str, code: str, username: str) -> bool:
    return _send(
        subject=f"Reset your {BRAND} password",
        template="password_reset",
        context={
            "to": to,
            "code": code,
            "username": username,
            "ttl_minutes": 30,
        },
    )


def send_password_changed(to: str, username: str) -> bool:
    return _send(
        subject=f"Your {BRAND} password was changed",
        template="password_changed",
        context={"to": to, "username": username},
    )


def send_booking_confirmation(to: str, reference: str, provider_name: str, starts_at: str) -> bool:
    return _send(
        subject=f"Booking {reference} confirmed",
        template="booking_confirmation",
        context={
            "to": to,
            "reference": reference,
            "provider_name": provider_name,
            "starts_at": starts_at,
        },
    )
