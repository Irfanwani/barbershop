"""Shared payment vocabulary.

Split out from `payments.models` so `bookings.models` can refer to it without
importing the payments app — which would be a circular import, since Payment
points back at Booking.
"""

from django.db import models


class PaymentKind(models.TextChoices):
    """Which part of what is owed a charge settles."""

    DEPOSIT = "deposit", "Deposit"
    BALANCE = "balance", "Balance"
    FULL = "full", "Paid in full"
    #: Not part of what is owed for the appointment. A tip is a separate act
    #: of generosity, and folding it into the booking total would let it move
    #: the deposit split, the platform fee, and anything measured off "total".
    TIP = "tip", "Tip"
