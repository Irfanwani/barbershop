"""Talking to a WhatsApp provider.

One module, one interface, three shapes of provider behind it. Everything the
rest of the app knows about WhatsApp is :func:`send`; everything it knows about
MSG91, Twilio or GXT is in here.

Why a boundary at all: the send path runs on every booking confirmation, so it
has to be safe when nothing is configured. A deployment with no WhatsApp
provider loses confirmations, not bookings - the same rule the rest of the
notifications follow.

Two things this deliberately does *not* do:

- **It does not raise.** A provider being down must not fail the booking that
  triggered the message. Callers that care read the status off the row.
- **It does not pretend a send is a delivery.** It returns what the gateway
  said, and the row keeps "sent" rather than "delivered" until a webhook says
  otherwise. Confusing the two is how an integration reports 100% delivery for
  messages that went nowhere.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10


@dataclass
class SendResult:
    ok: bool
    provider_message_id: str = ""
    reason: str = ""

    def as_payload(self) -> dict:
        return {
            "id": self.provider_message_id,
            "status": "sent" if self.ok else "failed",
        }


def configured() -> bool:
    """Whether there is a provider to talk to.

    Read from settings rather than sniffed from the URL, so a deployment can be
    switched off without a code change and so a test can turn it off on
    purpose.
    """
    return bool(settings.WHATSAPP_PROVIDER and settings.WHATSAPP_ACCOUNT_SID)


def _provider() -> str:
    return (settings.WHATSAPP_PROVIDER or "").strip().lower()


def send(*, to: str, body: str, idempotency_key: str) -> SendResult:
    """Send one message.

    The key is passed to the provider as its own idempotency token, because the
    local unique index only stops *our* duplicates - it cannot stop the one
    where the request succeeded and the connection dropped before we heard
    about it, which is precisely the case where we retry.
    """
    if not to:
        return SendResult(ok=False, reason="no number")

    if not configured():
        logger.debug("No WhatsApp provider configured; not sending %r", body[:40])
        return SendResult(ok=False, reason="not configured")

    handler = {
        "twilio": _send_twilio,
        "msg91": _send_msg91,
        "gxt": _send_gxt,
    }.get(_provider())

    if handler is None:
        logger.warning("Unknown WhatsApp provider %r; not sending", _provider())
        return SendResult(ok=False, reason=f"unknown provider {_provider()}")

    try:
        return handler(to=to, body=body, idempotency_key=idempotency_key)
    except requests.RequestException as exc:
        # Logged and swallowed: the booking that triggered this has already
        # succeeded and must not be rolled back by a provider outage.
        logger.warning("WhatsApp send failed for %s: %s", to, exc)
        return SendResult(ok=False, reason=str(exc)[:200])


def _send_twilio(*, to: str, body: str, idempotency_key: str) -> SendResult:
    """Twilio's content API, which is what most of the world uses.

    Twilio keys on ``Idempotency-Key`` for a 24-hour window, so a retry inside
    that window returns the original message rather than sending a second.
    """
    response = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{settings.WHATSAPP_ACCOUNT_SID}/Messages.json",
        data={
            "To": f"whatsapp:{to}",
            "From": f"whatsapp:{settings.WHATSAPP_FROM}",
            "Body": body,
        },
        auth=(settings.WHATSAPP_ACCOUNT_SID, settings.WHATSAPP_AUTH_TOKEN),
        headers={"Idempotency-Key": idempotency_key},
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        return SendResult(ok=False, reason=response.text[:200])
    payload = response.json()
    return SendResult(
        ok=True,
        provider_message_id=str(payload.get("sid", "")),
    )


def _send_msg91(*, to: str, body: str, idempotency_key: str) -> SendResult:
    """MSG91's transactional route, keyed on our own reference field."""
    response = requests.post(
        "https://control.msg91.com/api/v5/flow/",
        json={
            "template_id": settings.WHATSAPP_TEMPLATE_ID,
            "sender": settings.WHATSAPP_FROM,
            "short_url": "0",
            "recipients": [{"mobiles": to, "message": body}],
            # Their reference travels with the message and comes back on the
            # status callback, which is how a delivery is matched back to a row.
            "reference": idempotency_key,
        },
        headers={"authkey": settings.WHATSAPP_AUTH_TOKEN},
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        return SendResult(ok=False, reason=response.text[:200])
    payload = response.json()
    # MSG91 answers 200 with a per-recipient error list, so a 200 alone is not
    # a send.
    if payload.get("type") == "error" or not payload.get("data"):
        return SendResult(ok=False, reason=str(payload.get("message", ""))[:200])
    return SendResult(ok=True, provider_message_id=idempotency_key)


def _send_gxt(*, to: str, body: str, idempotency_key: str) -> SendResult:
    response = requests.post(
        "https://api.gxt.cloud/api/v1/messages",
        json={
            "from": settings.WHATSAPP_FROM,
            "to": to,
            "text": body,
            "reference": idempotency_key,
        },
        headers={"Authorization": f"Bearer {settings.WHATSAPP_AUTH_TOKEN}"},
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        return SendResult(ok=False, reason=response.text[:200])
    payload = response.json()
    message_id = payload.get("messageId") or payload.get("id") or idempotency_key
    return SendResult(ok=True, provider_message_id=str(message_id))
