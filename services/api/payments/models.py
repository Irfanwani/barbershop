"""Razorpay orders and their settlement.

The single most serious hole in the old API: ``PUT /api/payments/createorder``
took an appointment id in the request body and set ``paid=True`` on it, having
checked only that *someone* was authenticated. Any user could mark any booking
paid, and any booking.

Here, payment state is only ever advanced by a webhook whose HMAC signature has
been verified against the shared secret. The client cannot mark its own booking
paid, however it phrases the request.
"""

from __future__ import annotations

from django.db import models

from core.models import TimeStampedModel
from core.money import CURRENCY, format_minor
from payments.choices import PaymentKind


class PaymentStatus(models.TextChoices):
    CREATED = "created", "Order created"
    ATTEMPTED = "attempted", "Payment attempted"
    CAPTURED = "captured", "Captured"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"


class LedgerEntry(TimeStampedModel):
    """One line in a provider's financial history.

    Append-only and immutable. The balance a provider sees is the sum of these,
    never a stored figure, so it cannot drift from what happened and it can
    always be explained line by line. A correction is a new, opposite entry.

    Sign convention: **positive means the provider is owed money.** A payout is
    negative, because so is everything else that leaves their balance.
    """

    class Status(models.TextChoices):
        #: Earned, but the booking has not finished, so it could still be
        #: refunded or turn into a no-show.
        PENDING = "pending", "Pending"
        #: Earned and no longer at risk.
        CLEARED = "cleared", "Cleared"
        #: Sent to the provider's bank.
        PAID_OUT = "paid_out", "Paid out"
        #: A withdrawal that was requested and never happened. The row is kept
        #: — it is the record that the request was made and why it failed — but
        #: it is excluded from every balance. Deleting it would leave no trace
        #: that we asked a bank to pay out at all.
        VOIDED = "voided", "Voided"

    provider = models.ForeignKey(
        "providers.ProviderProfile", on_delete=models.CASCADE, related_name="ledger"
    )

    kind = models.CharField(max_length=32)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.CLEARED, db_index=True
    )

    amount = models.IntegerField(help_text="Positive is owed to the provider.")
    currency = models.CharField(max_length=3, default=CURRENCY)

    #: A booking reference, a payout id, or anything else this line refers to.
    reference = models.CharField(max_length=64, blank=True, default="")
    description = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "payments_ledger_entry"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["provider", "-created_at"]),
            models.Index(fields=["provider", "status"]),
            models.Index(fields=["reference"]),
        ]
        constraints = [
            # A zero line explains nothing and only adds noise to a statement.
            models.CheckConstraint(
                condition=~models.Q(amount=0), name="payments_ledger_amount_nonzero"
            )
        ]

    def __str__(self) -> str:
        return f"{self.provider.display_name} {self.kind} {format_minor(self.amount)}"

    @property
    def amount_display(self) -> str:
        return format_minor(self.amount, self.currency)


class Payment(TimeStampedModel):
    """One charge against a booking.

    One-to-many, because a booking can now be charged twice: a deposit to
    secure the slot and the balance on arrival. One-to-one made a second charge
    impossible to even store.

    ``kind`` is what keeps them apart. A deposit that is captured must never be
    read as "the booking is paid in full", and a balance that is captured must
    not re-confirm a booking the customer walked out on.
    """

    class PaymentMethod(models.TextChoices):
        RAZORPAY = "razorpay", "Razorpay"
        CASH = "cash", "Cash at the shop"

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.CASCADE, related_name="payments"
    )
    kind = models.CharField(
        max_length=16,
        choices=PaymentKind.choices,
        default=PaymentKind.FULL,
        help_text="Which part of what is owed this charge settles.",
    )

    razorpay_order_id = models.CharField(max_length=64, unique=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    razorpay_signature = models.CharField(max_length=256, blank=True, default="")

    amount = models.PositiveIntegerField(help_text="In the smallest currency unit.")
    currency = models.CharField(max_length=3, default=CURRENCY)

    status = models.CharField(
        max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.CREATED, db_index=True
    )
    method = models.CharField(
        max_length=16, choices=PaymentMethod.choices, default=PaymentMethod.RAZORPAY
    )

    captured_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True, default="")
    refunded_at = models.DateTimeField(null=True, blank=True)
    refund_id = models.CharField(max_length=64, blank=True, default="")
    #: Running total. A refund can be partial, and a second one is legal, so a
    #: boolean is not enough to know what has gone back.
    refunded_amount = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "payments_payment"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["booking", "kind", "status"]),
        ]
        constraints = [
            # At most one *captured* charge per part. Several attempts may
            # exist at once — a customer who abandons checkout and comes back
            # needs to be able to try again — but only one of them can ever
            # have taken the money.
            models.UniqueConstraint(
                fields=["booking", "kind"],
                condition=models.Q(status="captured"),
                name="payments_one_captured_charge_per_kind",
            )
        ]

    def __str__(self) -> str:
        return f"{self.razorpay_order_id} · {format_minor(self.amount)} · {self.status}"

    @property
    def is_captured(self) -> bool:
        return self.status == PaymentStatus.CAPTURED

    @property
    def amount_display(self) -> str:
        return format_minor(self.amount, self.currency)
