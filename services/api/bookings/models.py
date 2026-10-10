"""Bookings between a customer and a provider.

Two ideas carry the weight here.

**The server prices the booking.** A booking request names service ids. The API
looks up each service, computes the total, and stores it. A client that sends
its own number is ignored. See
[ADR 0003](../../../docs/decisions/0003-server-authoritative-pricing.md).

**Line items snapshot their price.** ``BookingItem`` copies the service name and
unit price at the moment of booking, so raising prices tomorrow does not
retroactively change yesterday's invoice. The old schema stored
``services`` as a pipe-delimited string — unqueryable, no foreign keys, capped
at 1000 characters — and a single mutable ``totalcost``.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from accounts.models import User
from core.models import TimeStampedModel
from core.money import CURRENCY, format_minor
from providers.models import ProviderProfile, Service

REFERENCE_PREFIX = "BK"
REFERENCE_LENGTH = 6
_REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1


def generate_reference() -> str:
    """A short booking reference, e.g. ``BK-7QK4M2``.

    Customer-visible, so it must not be guessable. Sequential ids were: ``BK-1``,
    ``BK-2`` would leak the entire booking history to anyone who opened the app.
    """
    body = "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(REFERENCE_LENGTH))
    return f"{REFERENCE_PREFIX}-{body}"


class BookingStatus(models.TextChoices):
    """Booking lifecycle.

    The old boolean pair (``paid``, plus a row deleted on cancel) could not
    distinguish "customer cancelled" from "provider cancelled", and left no
    record of a cancellation at all.
    """

    PENDING_PAYMENT = "pending_payment", "Awaiting payment"
    AWAITING_CONFIRMATION = "awaiting_confirmation", "Awaiting provider confirmation"
    CONFIRMED = "confirmed", "Confirmed"
    COMPLETED = "completed", "Completed"
    CANCELLED_BY_CUSTOMER = "cancelled_by_customer", "Cancelled by customer"
    CANCELLED_BY_PROVIDER = "cancelled_by_provider", "Cancelled by provider"
    NO_SHOW = "no_show", "No show"
    REFUNDED = "refunded", "Refunded"

    @property
    def is_terminal(self) -> bool:
        return self in {
            BookingStatus.COMPLETED,
            BookingStatus.CANCELLED_BY_CUSTOMER,
            BookingStatus.CANCELLED_BY_PROVIDER,
            BookingStatus.NO_SHOW,
            BookingStatus.REFUNDED,
        }

    @property
    def is_cancelled(self) -> bool:
        return self in {
            BookingStatus.CANCELLED_BY_CUSTOMER,
            BookingStatus.CANCELLED_BY_PROVIDER,
        }


#: Statuses that occupy a time slot and so block other bookings.
BLOCKING_STATUSES = (
    BookingStatus.PENDING_PAYMENT,
    BookingStatus.AWAITING_CONFIRMATION,
    BookingStatus.CONFIRMED,
    BookingStatus.COMPLETED,
)


class Booking(TimeStampedModel):
    """One appointment.

    ``starts_at`` is stored in UTC. The old implementation trusted a
    ``currentdatetime`` string sent by the phone to decide whether a slot was in
    the past — so setting the clock forward let you book yesterday.
    """

    reference = models.CharField(
        max_length=16, unique=True, db_index=True, default=generate_reference
    )

    customer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="bookings",
        limit_choices_to={"role": "customer"},
    )
    provider = models.ForeignKey(ProviderProfile, on_delete=models.CASCADE, related_name="bookings")

    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()

    status = models.CharField(
        max_length=32, choices=BookingStatus.choices, default=BookingStatus.PENDING_PAYMENT
    )

    # Computed server-side by core.money.quote. Never read from the request.
    subtotal = models.PositiveIntegerField(default=0)
    platform_fee = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default=CURRENCY)

    notes = models.TextField(blank=True, default="", max_length=500)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=200, blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bookings_booking"
        ordering = ["-starts_at"]
        indexes = [
            models.Index(fields=["provider", "starts_at"]),
            models.Index(fields=["customer", "-starts_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["provider", "status", "starts_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")), name="bookings_ends_after_starts"
            ),
            models.CheckConstraint(
                condition=Q(total__gte=F("subtotal")), name="bookings_total_gte_subtotal"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} · {self.customer} @ {self.provider} · {self.starts_at:%Y-%m-%d %H:%M}"

    @property
    def duration_minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)

    @property
    def total_display(self) -> str:
        return format_minor(self.total, self.currency)

    @property
    def can_be_cancelled(self) -> bool:
        return self.status not in {
            BookingStatus.COMPLETED,
            BookingStatus.CANCELLED_BY_CUSTOMER,
            BookingStatus.CANCELLED_BY_PROVIDER,
            BookingStatus.REFUNDED,
        }

    @property
    def is_paid(self) -> bool:
        payment = getattr(self, "payment", None)
        return bool(payment and payment.is_captured)

    def minutes_until_start(self) -> int:
        return int((self.starts_at - timezone.now()).total_seconds() // 60)


class BookingItem(TimeStampedModel):
    """One line of a booking, with the price frozen at the time of booking.

    ``service`` is nullable and set to ``NULL`` when a service is deleted, so
    deleting a menu item does not destroy the financial record of an appointment
    that already used it.
    """

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="items")

    service = models.ForeignKey(
        Service, on_delete=models.SET_NULL, null=True, blank=True, related_name="booking_items"
    )

    # Snapshots. These are the authoritative record of what was agreed.
    name = models.CharField(max_length=100)
    unit_price = models.PositiveIntegerField(help_text="In the smallest currency unit.")
    quantity = models.PositiveSmallIntegerField(default=1)
    duration_minutes = models.PositiveSmallIntegerField(default=30)

    class Meta:
        db_table = "bookings_booking_item"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1), name="bookings_item_quantity_gte_1"
            )
        ]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.name} @ {format_minor(self.unit_price)}"  # noqa: RUF001

    @property
    def line_total(self) -> int:
        return self.unit_price * self.quantity


class SlotAvailability(models.Model):
    """Pre-computed answer to "is this slot free?".

    Not a source of truth — :meth:`Booking.is_slot_available` still re-checks at
    write time, because caching a booking decision invites double-booking. This
    exists so the provider's calendar screen does not run a range query per slot
    of the day.
    """

    provider = models.ForeignKey(ProviderProfile, on_delete=models.CASCADE, related_name="slots")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    is_available = models.BooleanField(default=True)
    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="+", null=True, blank=True
    )

    class Meta:
        db_table = "bookings_slot_availability"
        indexes = [models.Index(fields=["provider", "starts_at"])]

    def __str__(self) -> str:
        return f"{self.provider_id} @ {self.starts_at:%Y-%m-%d %H:%M} ({'free' if self.is_available else 'taken'})"


def default_booking_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """The bookable window: from the next half hour, for the next 30 days."""
    now = now or timezone.now()
    start = (now + timedelta(minutes=29)).replace(second=0, microsecond=0)
    start += timedelta(minutes=(30 - start.minute) % 30)
    return start, start + timedelta(days=30)


def is_slot_available(
    provider: ProviderProfile,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking: int | None = None,
) -> bool:
    """Whether the provider is free for the given interval.

    Uses a simple half-open interval overlap: ``starts_at < other.ends_at`` and
    ``ends_at > other.starts_at``. A 30-minute booking ending exactly when the
    next begins is not a conflict, which is what customers expect.
    """
    conflicts = Booking.objects.filter(
        provider=provider,
        status__in=BLOCKING_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    if exclude_booking:
        conflicts = conflicts.exclude(pk=exclude_booking)
    return not conflicts.exists()


def provider_has_capacity(
    provider: ProviderProfile, starts_at: datetime, ends_at: datetime
) -> bool:
    """Whether the shop has a free chair at that time.

    A provider with four employees can run four simultaneous bookings. The old
    check compared a round-tripped timestamp string against ``employee_count``
    and silently swallowed every exception with ``except: pass`` — so any error
    in that comparison meant "always allow", i.e. double-booking by default.
    """
    overlapping = Booking.objects.filter(
        provider=provider,
        status__in=BLOCKING_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).count()
    return overlapping < max(provider.employee_count, 1)


def slot_grid(provider: ProviderProfile, days: int = 14) -> list[tuple[datetime, datetime]]:
    """Every bookable interval for the next ``days``, aligned to the slot grid.

    Reads as a schedule, which is what a customer's calendar screen wants.
    """
    step = timedelta(minutes=provider.slot_interval_minutes or 30)
    window_start, window_end = default_booking_window()
    window_end = min(window_end, timezone.now() + timedelta(days=days))

    slots: list[tuple[datetime, datetime]] = []
    cursor = window_start
    while cursor < window_end:
        if is_within_working_hours(provider, cursor, cursor + step):
            slots.append((cursor, cursor + step))
        cursor += step
    return slots


def next_free_slot(provider: ProviderProfile) -> datetime | None:
    """The soonest interval the provider is free for, or None."""
    for starts_at, ends_at in slot_grid(provider, days=7):
        if is_slot_available(provider, starts_at, ends_at) and provider_has_capacity(
            provider, starts_at, ends_at
        ):
            return starts_at
    return None


def is_within_working_hours(
    provider: ProviderProfile, starts_at: datetime, ends_at: datetime
) -> bool:
    local_start = timezone.localtime(starts_at)
    local_end = timezone.localtime(ends_at)
    return (
        provider.opening_time <= local_start.time()
        and local_end.time() <= provider.closing_time
        and local_start.date() == local_end.date()
    )


AUTH_USER_MODEL = settings.AUTH_USER_MODEL
