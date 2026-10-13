"""The WhatsApp webhook.

Unauthenticated, by necessity: WhatsApp signs the request rather than carrying
a token, so authenticity comes entirely from an HMAC over the raw body, checked
before the body is parsed. The same shape as the Razorpay webhook, for the same
reason and with the same failure mode: if the signature is wrong, nothing
happens at all.

Three rules, each of which exists because breaking it is expensive:

- **A redelivery must do nothing twice.** Every inbound message carries the
  provider's id, which is unique here. WhatsApp redelivers webhooks, and a
  reply that cancels a booking twice is a booking cancelled against two
  different fee policies.
- **A status is only ever moved forward.** Providers send these out of order,
  so a late "sent" must not walk a "delivered" back to looking undelivered.
- **Every event is acknowledged.** A non-2xx makes WhatsApp retry forever,
  including for an event we deliberately ignored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from messaging.outbound import apply_delivery_status, record_reply

logger = logging.getLogger(__name__)


def verify_signature(body: bytes, signature: str) -> bool:
    """Check the HMAC over the raw body.

    ``compare_digest`` rather than ``==``, so a caller cannot learn the
    signature one byte at a time.
    """
    secret = settings.WHATSAPP_WEBHOOK_SECRET
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


class WhatsAppWebhookView(APIView):
    """Inbound delivery statuses and replies."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    @extend_schema(
        operation_id="messaging_whatsapp_webhook",
        summary="WhatsApp callbacks",
        description=(
            "Delivery statuses and customer replies. Signed rather than "
            "authenticated; events are idempotent by the provider's own "
            "message id."
        ),
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        raw = request.body

        signature = request.headers.get("X-WhatsApp-Signature", "")
        if not verify_signature(raw, signature):
            # Nothing is parsed, nothing is recorded. A forged webhook that
            # cancels somebody's booking is the whole attack.
            logger.warning("Rejected WhatsApp webhook with a bad signature")
            return Response({"error": "bad signature"}, status=403)

        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return Response({"error": "bad json"}, status=400)

        handled = 0
        for event in _events(payload):
            try:
                if _handle(event):
                    handled += 1
            except Exception:
                # Logged and swallowed. Returning non-2xx would make WhatsApp
                # redeliver the whole batch, including the events that already
                # worked.
                logger.exception("Could not handle a WhatsApp event")

        # Always 2xx for anything we understood, including events we ignored.
        return Response({"handled": handled})


def _events(payload: dict) -> list[dict]:
    """Every event in a batch, whatever shape this provider uses.

    Twilio nests under ``MessageStatus``/``Body``, MSG91 uses ``type`` and
    ``message``, GXT uses ``messageId``. Normalised to a flat list here so the
    handler does not need to know which provider is configured.
    """
    for key in ("messages", "events", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    # A single message, as Twilio sends it for one status callback.
    if any(key in payload for key in ("MessageSid", "MessageStatus", "messageId", "type")):
        return [payload]
    return []


def _handle(event: dict) -> bool:
    """Deal with one event. Returns whether anything was recorded."""
    if _is_inbound(event):
        return _handle_reply(event)
    return _handle_status(event)


def _is_inbound(event: dict) -> bool:
    return bool(event.get("From") or event.get("from") or event.get("inbound"))


def _handle_reply(event: dict) -> bool:
    sender = str(event.get("From") or event.get("from") or "")
    body = str(event.get("Body") or event.get("body") or event.get("text") or "")
    message_id = str(event.get("MessageSid") or event.get("messageId") or event.get("id") or "")
    if not sender or not message_id:
        logger.info("Ignoring an inbound WhatsApp message with no sender or id")
        return False

    record_reply(sender=sender, body=body, provider_message_id=message_id)
    return True


def _handle_status(event: dict) -> bool:
    message_id = str(
        event.get("MessageSid")
        or event.get("messageId")
        or event.get("message_id")
        or event.get("reference")
        or ""
    )
    if not message_id:
        return False

    status = str(event.get("MessageStatus") or event.get("status") or event.get("event") or "")
    error = str(event.get("ErrorDescription") or event.get("error") or "")

    message = apply_delivery_status(provider_message_id=message_id, status=status, error=error)
    return message is not None
