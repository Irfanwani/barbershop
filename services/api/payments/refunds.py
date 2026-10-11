"""Refunds.

The scaffolding for this has been here since the beginning and has never run:
`PaymentStatus.REFUNDED`, `Payment.refunded_at` and `Payment.refund_id` all
exist, and nothing ever wrote them. So a cancelled-and-paid booking had no way
to give the money back except a manual one, and the late-cancel fee had nowhere
to go.

Two properties worth stating up front:

- **A refund is asynchronous.** Razorpay tells us it was *accepted*, not that it
  landed. The refund id is recorded immediately and the final state is settled
  by webhook, so a slow gateway cannot leave a booking looking refunded when it
  is not.
- **Refunds are capped at what was actually taken.** Recording a refund larger
  than the payment would let a shop mint money out of a cancellation.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from payments.models import Payment, PaymentStatus

logger = logging.getLogger(__name__)


class RefundError(Exception):
    """The refund was refused before it was sent. Surfaced as a 400."""


class GatewayUnavailable(RefundError):
    """Razorpay could not be reached. Worth retrying; worth saying so."""


def refundable(payment: Payment) -> int:
    """How much of this payment can still be given back."""
    if not payment.is_captured:
        return 0
    return max(payment.amount - (payment.refunded_amount or 0), 0)


def send_refund(payment: Payment, amount: int | None = None) -> Payment:
    """Ask Razorpay to refund a payment.

    Cash payments are settled by the shop itself, so there is nothing to send —
    the booking is marked refunded and the money is moved by whoever took it.
    """
    if payment.method == Payment.PaymentMethod.CASH:
        return _mark_refunded(payment, payment.amount, note="settled in cash")

    amount = amount or refundable(payment)
    if amount <= 0:
        raise RefundError("That payment has already been refunded in full.")
    if amount > refundable(payment):
        raise RefundError("That is more than was paid on this booking.")

    from payments.services import create_refund

    try:
        result = create_refund(
            payment_id=payment.razorpay_payment_id,
            amount=amount,
            notes={"payment": str(payment.id)},
        )
    except Exception as exc:
        logger.exception("Razorpay refused a refund for payment %s", payment.id)
        raise GatewayUnavailable(
            "We could not start that refund. Please try again in a moment."
        ) from exc

    return _mark_refunded(payment, amount, refund_id=result.get("id", ""))


def _mark_refunded(
    payment: Payment, amount: int, *, refund_id: str = "", note: str = ""
) -> Payment:
    refunded_total = (payment.refunded_amount or 0) + amount
    fully_refunded = refunded_total >= payment.amount

    payment.refunded_amount = refunded_total
    payment.refunded_at = timezone.now()
    if refund_id:
        payment.refund_id = refund_id[:64]
    if fully_refunded:
        payment.status = PaymentStatus.REFUNDED

    payment.save(
        update_fields=[
            "refunded_amount",
            "refunded_at",
            "refund_id",
            "status",
            "failure_reason",
            "updated_at",
        ]
    )

    logger.info(
        "Refunded %s of %s on payment %s%s",
        amount,
        payment.amount,
        payment.id,
        f" ({note})" if note else "",
    )
    return payment


@transaction.atomic
def refund_booking_deposit(booking, *, forfeited: int) -> list[Payment]:
    """Give back what a cancellation promised.

    `forfeited` comes from the booking's frozen policy, so the amount refunded
    is the amount the customer was told at cancellation time rather than one
    recomputed now.
    """
    from bookings.policy import refundable_for

    deposit_payments = [
        payment
        for payment in booking.payments.select_for_update().all()
        if payment.kind == "deposit" and payment.is_captured
    ]
    if not deposit_payments:
        return []

    promised = refundable_for(booking, forfeited=forfeited)
    already = sum(payment.refunded_amount or 0 for payment in deposit_payments)
    outstanding = max(promised - already, 0)

    if outstanding <= 0:
        return []

    # Refund the oldest captured deposit first, so a partially refunded payment
    # is never left as the confusing one.
    for payment in deposit_payments:
        if outstanding <= 0:
            break
        take = min(outstanding, refundable(payment))
        if take <= 0:
            continue
        send_refund(payment, take)
        outstanding -= take

    booking.refresh_from_db()
    return [p for p in deposit_payments if (p.refunded_amount or 0) > 0]


def refund_booking_payment(booking, *, amount: int | None = None, reason: str = "") -> Payment:
    """Refund a balance the customer paid, at the provider's request.

    Blocked once the appointment happened: the service was had, and giving the
    money back for it is a decision the shop should not be able to make
    silently.
    """
    from bookings.models import BookingStatus

    if booking.status == BookingStatus.COMPLETED:
        raise RefundError("This appointment has already been completed.")

    balance_payment = next(
        (
            payment
            for payment in booking.payments.select_for_update().all()
            if payment.kind == "balance" and payment.is_captured
        ),
        None,
    )
    if balance_payment is None:
        raise RefundError("Nothing was paid towards the balance on this booking.")

    payment = send_refund(balance_payment, amount)
    if reason:
        payment.failure_reason = reason[:255]
        payment.save(update_fields=["failure_reason"])
    return payment


def reconcile(payment: Payment, remote: dict) -> Payment:
    """Settle a refund's final state from a gateway webhook."""
    status = remote.get("status", "")
    if status in {"processed", "refunded"}:
        payment.status = (
            PaymentStatus.REFUNDED
            if (payment.refunded_amount or 0) >= payment.amount
            else PaymentStatus.CAPTURED
        )
        payment.save(update_fields=["status", "updated_at"])
    elif status == "failed":
        payment.failure_reason = str(remote.get("error_description", "Refund failed"))[:255]
        payment.save(update_fields=["failure_reason", "updated_at"])
    return payment
