"""Moving a booking to a different time.

Rescheduling is not a cancel followed by a book, even though that is how it
has to work today. Cancelling loses the reference the customer has been
quoting, drops the reminders, breaks the review link, and — on a booking with
a deposit already paid — can charge them twice or refund them once and then
take it again. All of that for a change of hour.

Three things make it worth its own path:

**The same booking.** Same reference, same payments, same frozen items. The
appointment moved; the agreement did not change.

**The price is re-checked, not re-derived.** A service can have changed price
since. Silently charging the new one is a bait and switch; silently charging
the old one is a shop eating a cost it agreed to nowhere. So a changed price
stops the reschedule and is reported, and the move happens only once someone
says yes to the new number.

**The cancellation policy still applies.** Otherwise "I need a different time"
becomes a way to move an appointment on the day with no penalty at all — the
loophole every booking product has. Inside the window this is a cancellation
and a new booking, which is exactly what it would have been without this
feature, and the response says so plainly rather than pretending to move it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from bookings.models import (
    BLOCKING_STATUSES,
    Booking,
    BookingStatus,
    has_room,
    is_within_working_hours,
)
from providers.models import Service


class RescheduleRefused(Exception):
    """The move cannot happen, and the reason is the customer's to act on."""

    def __init__(self, message: str, *, code: str = "not_allowed"):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class PriceChanged(Exception):
    """The booking would cost something different at the new moment.

    Carries both numbers so the client can show the difference rather than
    making the customer remember what they thought they were paying.
    """

    old_total: int
    new_total: int
    old_subtotal: int
    new_subtotal: int

    @property
    def difference(self) -> int:
        return self.new_total - self.old_total

    def message(self) -> str:
        direction = "more" if self.difference > 0 else "less"
        return (
            f"This service now costs {format_minor(self.new_total)}, "
            f"{format_minor(abs(self.difference))} {direction} than the "
            f"{format_minor(self.old_total)} you agreed to."
        )


def format_minor(amount: int) -> str:
    from core.money import format_minor as render

    return render(amount, "INR")


#: Statuses a booking can still be moved from. A completed, cancelled or
#: expired appointment is history; moving it would be rewriting it.
MOVABLE_STATUSES = {
    BookingStatus.PENDING_PAYMENT,
    BookingStatus.AWAITING_CONFIRMATION,
    BookingStatus.CONFIRMED,
}


def can_reschedule(booking: Booking) -> bool:
    return booking.status in MOVABLE_STATUSES


def repriced(booking: Booking) -> tuple[int, int, list[str]]:
    """What this booking would cost now, as ``(subtotal, total, gone)``.

    ``gone`` names any service that has been retired or deleted since. They are
    excluded from the arithmetic — a missing line is not a free line — but the
    caller refuses the move rather than quietly booking the customer for
    something the shop no longer does.
    """
    booked = {item.service_id for item in booking.items.all() if item.service_id is not None}

    live = list(Service.objects.filter(pk__in=booked, provider=booking.provider, is_active=True))
    gone = sorted(
        item.name
        for item in booking.items.select_related("service")
        if item.service is None or not item.service.is_active
    )

    subtotal = sum(service.price for service in live)

    from core.money import compute_platform_fee

    fee = compute_platform_fee(subtotal, settings.PLATFORM_FEE_PERCENT)
    return subtotal, subtotal + fee, gone


@transaction.atomic
def reschedule(
    booking: Booking,
    starts_at: datetime,
    *,
    accept_price_change: bool = False,
) -> Booking:
    """Move a booking to a new time, keeping its reference and its payments."""
    if not can_reschedule(booking):
        raise RescheduleRefused(
            f"A {booking.get_status_display().lower()} booking cannot be moved."
        )

    if starts_at <= timezone.now():
        raise RescheduleRefused("That time has already passed. Pick a later slot.")

    duration = booking.ends_at - booking.starts_at
    ends_at = starts_at + duration

    if not is_within_working_hours(booking.provider, starts_at, ends_at):
        raise RescheduleRefused(
            f"{booking.provider.display_name} is open "
            f"{booking.provider.opening_time:%H:%M} to "
            f"{booking.provider.closing_time:%H:%M}."
        )

    named = booking.staff
    if named is not None and not named.is_open_on(starts_at.weekday()):
        raise RescheduleRefused(f"{named.name} does not work that day.")

    # The booking itself is excluded: it is moving out of its own slot, and
    # counting it would make moving to an adjacent slot look like a conflict
    # with itself.
    clash = Booking.objects.filter(
        provider=booking.provider,
        status__in=BLOCKING_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).exclude(pk=booking.pk)
    if clash.exists():
        raise RescheduleRefused("That slot is already taken. Pick another time.")

    if not has_room(
        booking.provider,
        starts_at,
        ends_at,
        exclude_booking=booking.pk,
        staff=booking.staff,
    ):
        raise RescheduleRefused("The shop has no free chair at that time.")

    subtotal, total, gone = repriced(booking)
    if gone:
        raise RescheduleRefused(
            f"{booking.provider.display_name} no longer offers "
            f"{', '.join(gone)}. Cancel and book something else instead.",
            code="service_gone",
        )

    if total != booking.total and not accept_price_change:
        raise PriceChanged(
            old_total=booking.total,
            new_total=total,
            old_subtotal=booking.subtotal,
            new_subtotal=subtotal,
        )

    booking.starts_at = starts_at
    booking.ends_at = ends_at
    booking.subtotal = subtotal
    booking.platform_fee = total - subtotal
    booking.total = total

    # The deposit split moves with the price. It is a percentage of the total,
    # and holding the old figure while the total changes is the sort of thing
    # that only shows up in a reconciliation three months later.
    from core.money import compute_deposit

    deposit_percent = max(
        (
            item.service.deposit_percent
            for item in booking.items.select_related("service")
            if item.service is not None
        ),
        default=0,
    )
    deposit, balance = compute_deposit(total, deposit_percent)
    booking.deposit = deposit
    booking.balance = balance

    booking.late_cancel_fee, _ = compute_deposit(deposit, booking.provider.late_cancel_fee_percent)

    booking.save()

    # Reminders were scheduled against the old time; they are rebuilt from the
    # booking, so nothing has to be unsent and nothing can go out at the old
    # hour.
    return booking


def late_window_message(booking: Booking) -> str:
    """Why a move this close to the appointment is a cancellation instead."""
    return (
        f"This appointment is inside the {booking.cancellation_window_hours}-hour "
        "cancellation window, so it cannot be moved — it has to be cancelled and "
        "booked again."
    )


def deadline(booking: Booking) -> datetime:
    return booking.starts_at - timedelta(hours=booking.cancellation_window_hours)
