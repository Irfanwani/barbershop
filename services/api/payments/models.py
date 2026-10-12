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

from django.conf import settings
from django.db import models
from django.utils import timezone

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

    #: For a tip, which barber it is for. Nullable, and meaningless for every
    #: other kind. Carried on the payment rather than only on the tip because
    #: the tip row is written at capture, and the provider's screen has to show
    #: what is still pending.
    staff = models.ForeignKey(
        "providers.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
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

    def captured_count_for_order(self) -> int:
        """How many captured payments exist for this payment's order.

        What the idempotency tests are really checking is that a retry did not
        produce a second charge, and this is the number that says so.
        """
        return Payment.objects.filter(
            razorpay_order_id=self.razorpay_order_id, status=PaymentStatus.CAPTURED
        ).count()


class IdempotencyRecord(models.Model):
    """What a request with a given key is doing, or did, so a retry cannot do
    it again.

    A client on a flaky connection retries. Without this, retrying
    `POST /payments/verify/` is not merely wasteful — it is a second chance to
    capture, and a payment that appears twice on a statement is the sort of thing
    a customer does not forgive.

    Stored rather than held in memory because a retry arrives seconds or
    minutes later, usually at a different process from the original.

    The request fingerprint is what makes this safe rather than merely
    convenient: a *different* request wearing a key that has been used is not a
    retry, it is a mistake, and answering it with the first response would hand
    back somebody else's receipt.
    """

    class State(models.TextChoices):
        #: Written *before* the view runs, so two requests arriving together
        #: collide on the insert instead of both doing the work. Recording only
        #: the finished response left a window in which a second request found
        #: nothing at all, and on a payment endpoint that window is a double
        #: capture.
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETE = "complete", "Complete"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="idempotency_records"
    )
    key = models.CharField(max_length=128)
    endpoint = models.CharField(max_length=64)
    fingerprint = models.CharField(max_length=64)

    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.COMPLETE,
        help_text="Rows written before reservations existed are all finished responses.",
    )

    #: The status and body to replay, as JSON. Stored rather than recomputed
    #: so a replay is byte-identical, including anything the gateway told us.
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "payments_idempotency_record"
        ordering = ["-created_at"]
        constraints = [
            # Scoped to the account as well as the endpoint: two people on one
            # device, or one person signing out and back in, must not collide.
            models.UniqueConstraint(
                fields=["user", "endpoint", "key"], name="payments_idempotency_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.endpoint} · {self.key}"

    @property
    def age_seconds(self) -> float:
        return (timezone.now() - self.created_at).total_seconds()

    @property
    def is_replayable(self) -> bool:
        """Only a finished request has an answer worth handing back again."""
        return self.state == self.State.COMPLETE and self.response_status is not None


class Tip(TimeStampedModel):
    """A tip on a completed appointment.

    Separate from the booking on purpose. A tip is not part of what the
    appointment cost, so it must not touch ``total``, the deposit split, or
    anything measured off the total. It is also not credited to the provider as
    revenue to which the platform takes a percentage: a fee on somebody's
    thank-you is the kind of thing a marketplace does once and is never
    forgiven for.

    One row per payment. A ``OneToOne`` on the payment, so "a tip is paid once"
    is a database statement rather than a convention.
    """

    booking = models.ForeignKey("bookings.Booking", on_delete=models.CASCADE, related_name="tips")
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tips_given"
    )
    provider = models.ForeignKey(
        "providers.ProviderProfile", on_delete=models.CASCADE, related_name="tips_received"
    )
    #: Which barber, when the shop named them. Nullable because a tip can be
    #: for the shop rather than a person.
    staff = models.ForeignKey(
        "providers.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tips",
    )
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name="tip")
    amount = models.PositiveIntegerField(help_text="In the smallest currency unit.")

    class Meta:
        db_table = "payments_tip"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payments_tip_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.amount} on {self.booking_id}"
