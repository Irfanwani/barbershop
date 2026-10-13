"""Sending confirmations, and acting on the answers.

The acceptance for this feature is three sentences, and two of them are about
not doing something twice:

- **A booking sends one confirmation.** Keyed on what the message is *about* -
  ``booking-confirm:<reference>`` - with a unique index behind it, so "send the
  confirmation" is safe to call from a view, a task and a retry without
  thinking about which of them is first.
- **A webhook retry does not send a second.** Two separate mechanisms, because
  they fail differently: the local unique index covers our own retries, and the
  provider's idempotency token covers the case where *we* sent it, the gateway
  accepted it, and the connection dropped before we found out.
- **A reply that says "cancel" cancels the booking.** Parsed leniently, because
  people reply "cancel", "Cancelled", "pls cancel", "no longer need it" and a
  strict parser that only knows one of those is a booking that does not get
  cancelled.

Everything here is safe when no provider is configured: the message is recorded
as failed and the booking is unaffected.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from messaging import gateway
from messaging.models import (
    InboundReply,
    MessageKind,
    MessageStatus,
    ReplyIntent,
    WhatsAppMessage,
    booking_phone,
)

logger = logging.getLogger(__name__)


def confirmation_key(reference: str) -> str:
    """The idempotency key for a booking's confirmation."""
    return f"booking-confirm:{reference}"


def reminder_key(reference: str) -> str:
    return f"booking-reminder:{reference}"


def format_confirmation(booking) -> str:
    """The text a customer reads.

    Kept short. A long message is a message that costs more and reads less,
    and the link is the only part that has to be exact.
    """
    when = _friendly_when(booking)
    return (
        f"You're booked at {booking.provider.display_name}.\n\n"
        f"{when}\n"
        f"{booking.customer.display_name}, you are {booking.duration_minutes} minutes' "
        f"time.\n\n"
        f"Manage or cancel: {booking.manage_url()}\n\n"
        "Reply CANCEL to cancel, or YES to confirm you have got it."
    )


def format_cancelled(booking) -> str:
    return (
        f"Your booking at {booking.provider.display_name} on "
        f"{_friendly_when(booking)} has been cancelled.\n\n"
        "Reply to us here if that was not you."
    )


def format_rescheduled(booking) -> str:
    return (
        f"Your booking at {booking.provider.display_name} has moved to "
        f"{_friendly_when(booking)}.\n\n"
        f"Manage or cancel: {booking.manage_url()}"
    )


def _friendly_when(booking) -> str:
    """The appointment time in the shop's own words, not UTC."""
    local = booking.provider.localtime(booking.starts_at)
    return local.strftime("%a %d %b, %I:%M %p")


def send_confirmation(booking) -> WhatsAppMessage | None:
    """Send the booking's confirmation, once.

    Returns the row, which is either the one that already existed or the one
    just created. ``None`` when the customer has no number on file.
    """
    return _send_once(
        booking=booking,
        kind=MessageKind.BOOKING_CONFIRM,
        key=confirmation_key(booking.reference),
        body=format_confirmation(booking),
    )


def send_reminder(booking) -> WhatsAppMessage | None:
    return _send_once(
        booking=booking,
        kind=MessageKind.BOOKING_REMINDER,
        key=reminder_key(booking.reference),
        body=(
            f"Reminder: you're at {booking.provider.display_name} "
            f"{_friendly_when(booking)}.\n\n"
            f"{booking.manage_url()}\n\n"
            "Reply CANCEL if you can't make it."
        ),
    )


def notify_cancelled(booking) -> WhatsAppMessage | None:
    return _send_once(
        booking=booking,
        kind=MessageKind.BOOKING_CANCELLED,
        # Keyed on the booking, not on the cancellation count: telling somebody
        # twice is better than a booking that vanishes with no word.
        key=f"booking-cancelled:{booking.reference}",
        body=format_cancelled(booking),
    )


def notify_rescheduled(booking) -> WhatsAppMessage | None:
    return _send_once(
        booking=booking,
        kind=MessageKind.BOOKING_RESCHEDULED,
        key=f"booking-rescheduled:{booking.reference}",
        body=format_rescheduled(booking),
    )


def _send_once(*, booking: Booking, kind: str, key: str, body: str) -> WhatsAppMessage | None:
    """Create the row if it is not there, then send it.

    The row is inserted *before* the gateway is called, so two callers racing
    cannot both get past the check. The loser finds the unique constraint and
    stops.
    """
    recipient = booking_phone(booking)
    if not recipient:
        logger.debug("Booking %s has no number; not messaging", booking.reference)
        return None

    try:
        with transaction.atomic():
            message = WhatsAppMessage.objects.create(
                booking=booking,
                recipient=recipient,
                kind=kind,
                body=body,
                idempotency_key=key,
                status=MessageStatus.QUEUED,
            )
    except IntegrityError:
        # Already sent, or already being sent. Either way, not our business.
        existing = WhatsAppMessage.objects.filter(idempotency_key=key).first()
        logger.debug("WhatsApp %s already exists; not sending again", key)
        return existing

    _deliver(message)
    return message


def _deliver(message: WhatsAppMessage) -> None:
    """Hand a queued message to the gateway and record what came back."""
    result = gateway.send(
        to=message.recipient,
        body=message.body,
        idempotency_key=message.idempotency_key,
    )

    message.status = MessageStatus.SENT if result.ok else MessageStatus.FAILED
    message.provider_message_id = result.provider_message_id
    message.failure_reason = "" if result.ok else result.reason[:200]
    message.sent_at = timezone.now() if result.ok else None
    message.save(
        update_fields=[
            "status",
            "provider_message_id",
            "failure_reason",
            "sent_at",
            "updated_at",
        ]
    )


def retry_queued(*, older_than_minutes: int = 5, limit: int = 200) -> int:
    """Re-send anything that was queued and never came back.

    A provider that times out leaves a row at ``queued``. Without this the
    confirmation is simply lost, and the customer finds out at the shop.

    Only ``queued`` and ``failed`` are retried, never ``sent`` - a message the
    gateway accepted might have been delivered, and re-sending one of those
    costs money and annoys somebody for no gain.
    """
    cutoff = timezone.now() - timedelta(minutes=older_than_minutes)
    stuck = list(
        WhatsAppMessage.objects.filter(status__in=[MessageStatus.QUEUED, MessageStatus.FAILED])
        .filter(created_at__lte=cutoff)
        .order_by("id")[:limit]
    )

    for message in stuck:
        _deliver(message)
    if stuck:
        logger.info("Retried %s stuck WhatsApp messages", len(stuck))
    return len(stuck)


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------

#: Ordered most specific first, so "cannot make it" is not read as a plain
#: "cancel" by a looser pattern further down.
_CANCEL_PATTERNS = [
    r"\bcancel\b",
    r"\bcancelled\b",
    r"\bcancellation\b",
    r"\bcan'?t make\b",
    r"\bcannot make\b",
    r"\bno longer\b",
    r"\bwon'?t be able\b",
    r"\bwon'?t make\b",
    r"\bnot coming\b",
    r"\bplease cancel\b",
]

_RESCHEDULE_PATTERNS = [
    r"\breschedul",
    r"\bchange (?:the |my )?(?:time|slot|date)\b",
    r"\bdifferent (?:time|slot|date)\b",
    r"\bmove (?:it|my)\b",
    r"\bpostpone\b",
]

_CONFIRM_PATTERNS = [
    r"^\s*yes\b",
    r"\bconfirm",
    r"\bgot it\b",
    r"\bok\b",
    r"\bokay\b",
]

#: "thanks" is deliberately *not* in the confirm list. It is somebody
#: acknowledging what we said - and after a cancellation, reading it as a
#: further instruction is how a booking gets cancelled twice.


def parse_intent(body: str) -> str:
    """What somebody meant, from how they said it.

    Case-insensitive and prefix-tolerant, because a reply arriving as "CANCEL"
    and one arriving as "pls cancel my booking" are the same intent and only
    one of them is on any list anybody writes.
    """
    text = (body or "").strip().lower()
    if not text:
        return ReplyIntent.NONE

    for pattern in _CANCEL_PATTERNS:
        if re.search(pattern, text):
            return ReplyIntent.CANCEL

    for pattern in _RESCHEDULE_PATTERNS:
        if re.search(pattern, text):
            return ReplyIntent.RESCHEDULE

    for pattern in _CONFIRM_PATTERNS:
        if re.search(pattern, text):
            return ReplyIntent.CONFIRM

    return ReplyIntent.NONE


def find_booking_for(sender: str, body: str) -> Booking | None:
    """Which booking this reply is about.

    Matched on the number, which is the only thing a provider reliably gives
    us, and then narrowed to the booking it could plausibly refer to: the most
    recent one that is still live. A reply of "cancel" from somebody with three
    bookings should not silently cancel the one from last March.
    """
    customer = _customer_for_number(sender)
    if customer is None:
        return None

    live = list(
        Booking.objects.filter(
            customer=customer,
            status__in=[
                BookingStatus.AWAITING_CONFIRMATION,
                BookingStatus.CONFIRMED,
                BookingStatus.PENDING_PAYMENT,
            ],
        ).select_related("provider", "customer")
    )
    if not live:
        return None

    # A reference in the message wins over recency, when there is one.
    for booking in live:
        if booking.reference.lower() in (body or "").lower():
            return booking

    return max(live, key=lambda booking: booking.starts_at)


def _customer_for_number(sender: str):
    """The account this number belongs to, or ``None``.

    Every account with a phone is compared rather than matched with SQL: the
    number may be stored as "+919876543210", "09876543210" or "9876543210", and
    only the first two normalise to the same digits.
    """
    from accounts.models import User

    digits = "".join(ch for ch in (sender or "") if ch.isdigit())
    if not digits:
        return None
    for user in User.objects.filter(phone__isnull=False).exclude(phone="").only("id", "phone"):
        if booking_phone_for_user(user) == digits:
            return user
    return None


def booking_phone_for_user(user) -> str:
    """The same normalisation :func:`booking_phone` does, for a bare account."""
    raw = (user.phone or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if raw.startswith("+"):
        return digits
    from messaging.models import DEFAULT_COUNTRY_CODE

    return f"{DEFAULT_COUNTRY_CODE}{digits}" if len(digits) == 10 else digits


def record_reply(
    *, sender: str, body: str, provider_message_id: str, booking: Booking | None = None
) -> InboundReply | None:
    """Store a reply, and act on it. Once.

    The provider's message id is unique, because every WhatsApp provider
    redelivers webhooks and a reply that cancels a booking twice is a booking
    cancelled against two different fee policies.
    """
    try:
        with transaction.atomic():
            reply = InboundReply.objects.create(
                sender=sender,
                body=body,
                intent=parse_intent(body),
                provider_message_id=provider_message_id,
                booking=booking if booking is not None else find_booking_for(sender, body),
            )
    except IntegrityError:
        logger.debug("WhatsApp reply %s already seen", provider_message_id)
        return None

    _act(reply)
    return reply


def _act(reply: InboundReply) -> None:
    """Do what the reply asked, and say what happened."""
    from bookings.policy import apply_cancellation
    from payments.refunds import refund_booking_deposit

    if reply.intent == ReplyIntent.CANCEL and reply.booking_id is not None:
        booking = (
            Booking.objects.filter(pk=reply.booking_id)
            .select_related("customer", "provider")
            .first()
        )
        if booking is None:
            reply.handled_note = "Booking vanished"
        elif not booking.can_be_cancelled:
            reply.handled_note = f"Cannot cancel a {booking.get_status_display().lower()} booking"
        else:
            try:
                outcome = apply_cancellation(
                    booking, by_provider=False, reason="Cancelled by WhatsApp reply"
                )
                # Settle any deposit afterwards, so a gateway that refuses does
                # not make the cancellation look like it failed.
                try:
                    refund_booking_deposit(booking, forfeited=outcome.deposit_forfeited)
                except Exception as exc:
                    logger.warning("Could not refund %s: %s", booking.reference, exc)
                    reply.handled_note = "Cancelled, refund needs attention"
                else:
                    reply.handled_note = "Cancelled"
                notify_cancelled(booking)
            except Exception as exc:
                logger.warning("Could not cancel %s by reply: %s", booking.reference, exc)
                reply.handled_note = "Cancellation refused"
    elif reply.intent == ReplyIntent.RESCHEDULE and reply.booking_id is not None:
        # Deliberately not automated. A reschedule needs a new time, and nobody
        # who typed "reschedule" has told us which one.
        reply.handled_note = "Asked to reschedule - needs a time, so handled by a person"
    elif reply.intent == ReplyIntent.CONFIRM:
        reply.handled_note = "Acknowledged"
    else:
        reply.handled_note = "No booking matched" if reply.booking_id is None else "Not understood"

    reply.handled_at = timezone.now()
    reply.save(update_fields=["handled_at", "handled_note", "booking"])


def apply_delivery_status(
    *, provider_message_id: str, status: str, error: str = ""
) -> WhatsAppMessage | None:
    """Reconcile a delivery webhook back onto our row.

    Providers send these out of order and more than once, so a status is only
    ever moved forward: a "delivered" arriving after a "sent" sticks, and a
    late "sent" cannot walk it back to looking undelivered.
    """
    message = WhatsAppMessage.objects.filter(provider_message_id=provider_message_id).first()
    if message is None:
        logger.info("Delivery status for unknown message %s", provider_message_id)
        return None

    mapped = _map_status(status)
    if mapped is None:
        return message

    if not _is_forward(message.status, mapped):
        logger.debug("Ignoring out-of-order status %s for %s", status, provider_message_id)
        return message

    message.status = mapped
    updates = ["status", "updated_at"]
    if mapped == MessageStatus.DELIVERED and message.delivered_at is None:
        message.delivered_at = timezone.now()
        updates.append("delivered_at")
    if mapped == MessageStatus.FAILED and error:
        message.failure_reason = error[:200]
        updates.append("failure_reason")
    message.save(update_fields=updates)
    return message


#: Providers spell these a dozen ways.
_STATUS_NAMES = {
    MessageStatus.QUEUED: {"queued", "pending", "accepted", "submitted"},
    MessageStatus.SENT: {"sent", "sending", "processed"},
    MessageStatus.DELIVERED: {"delivered", "success", "delivered_to_device"},
    MessageStatus.READ: {"read", "seen"},
    MessageStatus.FAILED: {"failed", "error", "undelivered", "rejected"},
}

#: How far along each status is. Anything lower than where we already are is
#: ignored.
#: Plain strings rather than the enum members: the incoming status is a string,
#: and comparing a str against a dict keyed by a str-valued enum reads as a
#: type error to mypy while working fine at runtime.
_STATUS_RANK: dict[str, int] = {
    "queued": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
    # Failed is not "further along" than delivered - it is a different branch,
    # so it is ranked below delivered and only applies when nothing better has
    # happened.
    "failed": 0,
}


def _map_status(status: str) -> str | None:
    name = (status or "").strip().lower().replace("-", "_")
    for ours, theirs in _STATUS_NAMES.items():
        if name in theirs:
            return ours
    return None


def _is_forward(current: str, incoming: str) -> bool:
    """Whether ``incoming`` is news, given what we already know."""
    if incoming == current:
        return False
    # A failure is only news while we have not been told it arrived.
    if incoming == MessageStatus.FAILED:
        return _STATUS_RANK[str(current)] < _STATUS_RANK["delivered"]
    return _STATUS_RANK[str(incoming)] > _STATUS_RANK[str(current)]
