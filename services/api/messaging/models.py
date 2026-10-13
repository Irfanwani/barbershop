"""Outbound WhatsApp, and what came back.

Two tables, because they answer two different questions:

- ``WhatsAppMessage``: what we tried to say, to whom, and whether it went.
- ``InboundReply``: what somebody said back.

The first is the interesting one, and the reason for the ``idempotency_key`` is
the whole feature. WhatsApp is charged per message, a booking confirmation is
generated from code that can run twice (a retried request, a task that ran
twice), and a customer who gets the same confirmation four times is a customer
who stops reading them. So a confirmation is keyed on what it is *about*, not
on when it was sent: ``booking-confirm:<reference>``. The unique index means the
second attempt finds the first and does nothing.

The delivery-status column is not decoration. A message that was accepted by
the gateway has not been delivered, and "accepted" is the point at which most
integrations quietly declare success.
"""

from __future__ import annotations

from django.db import models

from core.models import TimeStampedModel

# Re-exported so Django's app registry resolves the related_name targets.
__all__ = [
    "InboundReply",
    "MessageKind",
    "MessageStatus",
    "ReplyIntent",
    "WhatsAppMessage",
    "booking_phone",
]


class MessageStatus(models.TextChoices):
    #: Written before the gateway is called. Anything that crashes between here
    #: and the response leaves a row saying "we were going to", which is how a
    #: retry knows what it still owes.
    QUEUED = "queued", "Queued"
    #: The gateway accepted it. Not delivered - accepted.
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    #: Seen by a human on a handset. The only status that means somebody read it.
    READ = "read", "Read"
    FAILED = "failed", "Failed"


class MessageKind(models.TextChoices):
    BOOKING_CONFIRM = "booking_confirm", "Booking confirmation"
    BOOKING_REMINDER = "booking_reminder", "Booking reminder"
    BOOKING_CANCELLED = "booking_cancelled", "Booking cancelled"
    BOOKING_RESCHEDULED = "booking_rescheduled", "Booking rescheduled"


class WhatsAppMessage(TimeStampedModel):
    """One outbound message, and its row in the ledger of what we said."""

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.CASCADE, related_name="whatsapp_messages"
    )
    recipient = models.CharField(max_length=20, help_text="As dialled, including the country code.")

    kind = models.CharField(max_length=32, choices=MessageKind.choices)
    body = models.TextField()

    #: What this message *is*, not when it was sent. The unique index on this
    #: is what makes "send a booking confirmation" safe to call from anywhere,
    #: twice, forever.
    idempotency_key = models.CharField(max_length=64, unique=True)

    status = models.CharField(
        max_length=16, choices=MessageStatus.choices, default=MessageStatus.QUEUED
    )
    #: The gateway's own id. Needed to match an inbound status webhook back to
    #: this row; without it, "delivered" has nothing to attach to.
    provider_message_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    failure_reason = models.CharField(max_length=200, blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "messaging_whatsappmessage"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["booking", "kind"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind} -> {self.recipient} ({self.status})"


class ReplyIntent(models.TextChoices):
    NONE = "none", "Not understood"
    CONFIRM = "confirm", "Yes"
    CANCEL = "cancel", "Cancel"
    RESCHEDULE = "reschedule", "Reschedule"


class InboundReply(TimeStampedModel):
    """Something somebody sent back.

    Kept whatever it said, including the parts that made no sense. A reply the
    app could not parse is still a reply from a customer, and discarding it
    means the next person to look has no way of knowing anybody tried to cancel.
    """

    booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="whatsapp_replies",
    )
    sender = models.CharField(max_length=20)
    body = models.TextField()
    intent = models.CharField(max_length=16, choices=ReplyIntent.choices, default=ReplyIntent.NONE)
    #: The gateway's id for the inbound message. Unique, because every provider
    #: redelivers webhooks and a reply that cancels a booking twice is a
    #: booking cancelled with two different fees.
    provider_message_id = models.CharField(max_length=64, unique=True)
    handled_at = models.DateTimeField(null=True, blank=True)
    handled_note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "messaging_inboundreply"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.sender}: {self.body[:40]}"


def booking_phone(booking) -> str:
    """The number to message, or "".

    Normalised to digits with a leading country code where we can work one out.
    Sending to a number in the wrong format is charged for and never arrives,
    so an unparseable number is better treated as no number at all.
    """
    raw = (booking.customer.phone or "").strip()
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if raw.startswith("+"):
        return digits
    if len(digits) == 10:
        return f"{DEFAULT_COUNTRY_CODE}{digits}"
    return digits


#: India runs on WhatsApp, so an Indian number is the common case. Overridable,
#: because a marketplace that grows has customers elsewhere.
DEFAULT_COUNTRY_CODE = "91"
