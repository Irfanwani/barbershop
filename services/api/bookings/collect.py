"""Collecting what is left at the counter.

A deposit secures the slot; the balance is settled in the chair. Most of this
category settles the balance in cash, because the customer is standing in front
of you and the card machine is slower than the cash box. So cash is a first
class way to close a booking out, not a fallback.

Two rules, both learned from the deposit feature:

- **A cash payment is a provider action.** It cannot be asserted by the
  customer, and it is never inferred from "the appointment ended".
- **Recording it does not change the booking's status.** Marking a booking
  `completed` is a separate decision — a customer who paid the balance and then
  walked out has still been paid.

Every entry is written through `record_payment` so the ledger of charges against
a booking has exactly one writer.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from payments.choices import PaymentKind
from payments.due import amount_due, default_kind
from payments.models import Payment, PaymentStatus

logger = logging.getLogger(__name__)


class NothingToCollect(Exception):
    """The booking is already settled. Handled as a 400, not a crash."""


def record_payment(
    booking: Booking,
    *,
    amount: int,
    method: str,
    kind: str | None = None,
    reference: str | None = None,
    note: str = "",
) -> Payment:
    """Write one charge against a booking.

    Refuses to record more than what is outstanding. A typo at the counter that
    over-records is harder to undo than one that is refused outright.
    """
    kind = kind or default_kind(booking)
    outstanding = amount_due(booking, kind)

    if outstanding <= 0:
        raise NothingToCollect("There is nothing left to collect on this booking.")
    if amount <= 0:
        raise NothingToCollect("That is not an amount worth recording.")
    if amount > outstanding:
        raise NothingToCollect(f"That is more than the {outstanding} still owed on this booking.")

    # Cash has no gateway id. A synthetic one keeps `razorpay_order_id` unique
    # and stops a cash row being confused with a gateway order later.
    return Payment.objects.create(
        booking=booking,
        kind=kind,
        method=method,
        amount=amount,
        currency=booking.currency,
        status=PaymentStatus.CAPTURED,
        captured_at=timezone.now(),
        razorpay_order_id=reference or f"cash:{booking.reference}:{kind}",
        failure_reason=note[:255],
    )


@transaction.atomic
def collect_cash(booking: Booking, amount: int, *, method: str, note: str = "") -> Payment:
    """Take the outstanding balance in cash, or any part of it.

    Called by the provider from the chair. The booking is locked for the
    duration so two tills cannot both record against the same last ₹100.
    """
    locked = (
        Booking.objects.select_for_update()
        .select_related("provider__user", "customer")
        .get(pk=booking.pk)
    )

    if locked.status not in {BookingStatus.CONFIRMED, BookingStatus.COMPLETED}:
        raise NothingToCollect(
            f"A {locked.get_status_display().lower()} booking has nothing to collect."
        )

    payment = record_payment(locked, amount=amount, method=method, note=note)
    logger.info("Recorded %s of %s against %s", amount, locked.reference, locked.currency)
    return payment


def settled_in_cash(booking: Booking) -> bool:
    """Whether the whole balance has been taken without touching a gateway."""
    return (
        booking.total > 0
        and booking.amount_paid >= booking.total
        and not booking.payments.filter(
            kind=PaymentKind.BALANCE, method=Payment.PaymentMethod.RAZORPAY
        ).exists()
    )


__all__ = [
    "NothingToCollect",
    "PaymentKind",
    "collect_cash",
    "record_payment",
    "settled_in_cash",
]
