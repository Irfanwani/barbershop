"""What is owed on a booking, and when.

The rule that matters: a deposit is not payment. Reading a captured deposit as
"this booking is paid" is the single easiest way to get deposits wrong, and it
leaves a shop with a customer who has staked ₹900 on a ₹3,000 colouring job and
nothing holding the rest.
"""

from __future__ import annotations

from payments.choices import PaymentKind


def amount_due(booking, kind: str) -> int:
    """How much a charge of this ``kind`` should be for.

    Always derived from the booking's own frozen numbers and what has actually
    been captured, never from anything the client sends.
    """
    paid = booking.amount_paid

    if kind == PaymentKind.DEPOSIT:
        # A deposit already captured means the slot is secured; nothing more is
        # due for it. Otherwise the deposit is what is owed.
        return 0 if booking.has_captured_deposit else booking.deposit

    if kind == PaymentKind.BALANCE:
        # The balance is what is left once the deposit is accounted for —
        # whether that deposit has been paid or is still outstanding. Charging
        # `total - paid` here would bill the deposit twice, because on a booking
        # where nothing is paid yet the deposit is not in `paid`.
        outstanding_deposit = 0 if booking.has_captured_deposit else booking.deposit
        return max(booking.total - paid - outstanding_deposit, 0)

    # FULL: everything still outstanding, whatever it is made of.
    return max(booking.total - paid, 0)


def default_kind(booking) -> str:
    """Which charge the customer owes next, without being told.

    A booking that needs a deposit and has none owes the deposit. Once that is
    paid the next charge is the balance. A booking with no deposit policy owes
    the whole thing as one charge.
    """
    if booking.deposit > 0 and not booking.has_captured_deposit:
        return PaymentKind.DEPOSIT

    if booking.balance > 0:
        return PaymentKind.BALANCE

    return PaymentKind.FULL


def requested_kind(request) -> str:
    """The kind the caller asked for, defaulting to what is owed next.

    An unrecognised value is ignored rather than trusted: this decides how much
    money to ask for, and a caller should not be able to name an arbitrary
    kind and get an arbitrary amount.
    """
    asked = (request.query_params.get("kind") or request.data.get("kind") or "").strip()
    if asked in dict(PaymentKind.choices):
        return asked
    return ""
