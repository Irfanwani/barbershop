"""Cancellation, and what it does to the money.

The policy is frozen on the booking, not read from the shop. That is the whole
design: if the deadline were looked up live, a shop could tighten its window on
Monday and a customer who booked on Sunday would find out they now owed money
they never agreed to.

The asymmetry is deliberate and one-directional:

- A **customer** cancelling late forfeits an agreed slice of their deposit.
  The slot is nearly gone and the shop has turned somebody away.
- A **provider** cancelling is always free. The shop still has the chair and the
  customer is not at fault, so charging them for the shop's own change of plan
  would be indefensible.

This module decides and records. Moving the money is
`payments.refunds`, because a Razorpay refund is asynchronous and belongs with
the rest of the gateway code rather than inside a booking transition.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from payments.choices import PaymentKind


@dataclass
class CancellationOutcome:
    """What a cancellation did, for the response and the audit trail."""

    by_provider: bool
    is_late: bool
    deposit_forfeited: int
    deposit_refundable: int
    message: str

    def as_dict(self) -> dict[str, object]:
        from core.money import format_minor

        return {
            "by_provider": self.by_provider,
            "is_late": self.is_late,
            "deposit_forfeited": self.deposit_forfeited,
            "deposit_forfeited_display": format_minor(self.deposit_forfeited),
            "deposit_refundable": self.deposit_refundable,
            "deposit_refundable_display": format_minor(self.deposit_refundable),
            "message": self.message,
        }


@transaction.atomic
def apply_cancellation(booking: Booking, *, by_provider: bool, reason: str) -> CancellationOutcome:
    """Cancel a booking and settle its deposit.

    Refuses to run on a booking that cannot be cancelled at all; the caller
    checks that first so the error reads like the rest of the API.
    """
    if not booking.can_be_cancelled:
        raise ValueError("This booking cannot be cancelled.")

    locked = (
        Booking.objects.select_for_update()
        .select_related("provider__user", "customer")
        .get(pk=booking.pk)
    )

    captured_deposit = next(
        (
            payment.amount
            for payment in locked.payments.all()
            if payment.kind == PaymentKind.DEPOSIT and payment.is_captured
        ),
        0,
    )

    if by_provider:
        # The shop has the chair. Everything the customer paid comes back.
        forfeited = 0
        message = "Cancelled by the shop. Your payment is being refunded in full."
    elif locked.is_late_cancellation():
        forfeited = min(captured_deposit, locked.late_cancel_fee)
        message = (
            f"Cancelled inside the {locked.cancellation_window_hours}h window. "
            f"{_money(forfeited)} of the deposit is kept to cover the slot."
            if forfeited
            else "Cancelled inside the cancellation window. Your deposit is still returned."
        )
    else:
        forfeited = 0
        message = "Cancelled in good time. Your deposit is being refunded in full."

    locked.status = (
        BookingStatus.CANCELLED_BY_PROVIDER if by_provider else BookingStatus.CANCELLED_BY_CUSTOMER
    )
    locked.cancelled_at = timezone.now()
    locked.cancellation_reason = reason[:200]
    locked.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])

    late = locked.is_late_cancellation(at=locked.cancelled_at)

    return CancellationOutcome(
        by_provider=by_provider,
        # A provider cancelling is never "late" — that word carries the
        # accusation, and the shop is the one who changed plan.
        is_late=late and not by_provider,
        deposit_forfeited=forfeited,
        deposit_refundable=max(captured_deposit - forfeited, 0),
        message=message,
    )


def _money(minor: int) -> str:
    from core.money import format_minor

    return format_minor(minor)


def refundable_for(booking: Booking, *, forfeited: int) -> int:
    """How much of a captured deposit comes back.

    Used by the refund flow. Kept here so the number that was promised at
    cancellation time is the number that is actually refunded.
    """
    captured_deposit = sum(
        payment.amount
        for payment in booking.payments.all()
        if payment.kind == PaymentKind.DEPOSIT and payment.is_captured
    )
    return max(captured_deposit - forfeited, 0)
