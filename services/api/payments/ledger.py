"""What a provider has earned, and what they have been paid.

This is the most serious gap in the platform. A provider can save bank details,
they are registered with Razorpay, and then there is no balance, no ledger, no
settlement and no way to withdraw. The supply side of the marketplace cannot get
paid through the product at all.

The whole model follows from one decision: **the balance is derived, never
stored.** Every figure is the sum of an append-only ledger, so it cannot drift
from what actually happened and it can always be explained line by line. A
stored balance that is updated in place is a balance that will eventually be
wrong with nothing to reconcile against.

Entries are immutable. A correction is a new, opposite entry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q, Sum

from providers.models import ProviderProfile

logger = logging.getLogger(__name__)


class EntryKind:
    """Why money moved.

    Plain strings rather than a Django TextChoices because the set is likely to
    grow and the values end up in reports.
    """

    EARNING = "earning"
    PLATFORM_FEE = "platform_fee"
    REFUND = "refund"
    LATE_CANCEL_FEE = "late_cancel_fee"
    PAYOUT = "payout"
    ADJUSTMENT = "adjustment"


@dataclass(frozen=True)
class Balance:
    """A provider's position, derived from the ledger."""

    pending: int
    cleared: int
    paid_out: int

    @property
    def total(self) -> int:
        """Everything the provider has earned and not been paid."""
        return self.pending + self.cleared

    def as_dict(self) -> dict[str, object]:
        from core.money import format_minor

        return {
            "pending": self.pending,
            "pending_display": format_minor(self.pending),
            "cleared": self.cleared,
            "cleared_display": format_minor(self.cleared),
            "paid_out": self.paid_out,
            "paid_out_display": format_minor(self.paid_out),
            "total": self.total,
            "total_display": format_minor(self.total),
        }


def balance_for(provider: ProviderProfile) -> Balance:
    """Everything the provider is owed and everything they have had."""
    from payments.models import LedgerEntry

    totals = LedgerEntry.objects.filter(provider=provider).aggregate(
        pending=Sum("amount", filter=Q(status=LedgerEntry.Status.PENDING)),
        cleared=Sum("amount", filter=Q(status=LedgerEntry.Status.CLEARED)),
        paid_out=Sum("amount", filter=Q(status=LedgerEntry.Status.PAID_OUT)),
    )
    # VOIDED entries are history and nothing else; they are in no total above.

    # Earnings accumulate as cleared and each payout draws them down, so the
    # balance is a running figure rather than a plain sum of one column. Clamped
    # at zero: a payout larger than the balance would otherwise leave a provider
    # owing money to the platform, which is the opposite of the point.
    paid_out = abs(totals["paid_out"] or 0)
    return Balance(
        pending=totals["pending"] or 0,
        cleared=max((totals["cleared"] or 0) - paid_out, 0),
        paid_out=paid_out,
    )


@transaction.atomic
def credit_earning(provider: ProviderProfile, *, gross: int, booking_reference: str = "") -> None:
    """Record a completed booking as money the provider has earned.

    Two entries, not one, because the provider and the platform were paid
    different amounts and a single net figure cannot be explained to either of
    them. A shop asking "why is this ₹270 not ₹300" deserves a row saying so.
    """
    from payments.models import LedgerEntry

    fee = _fee_for(gross)

    LedgerEntry.objects.create(
        provider=provider,
        kind=EntryKind.EARNING,
        # The booking price in full. The platform's share is the next line, so the
        # two sides of the split are visible rather than collapsed into a net
        # figure neither of them can explain.
        amount=gross,
        currency="INR",
        status=LedgerEntry.Status.PENDING,
        reference=booking_reference,
        description=f"Booking {booking_reference}" if booking_reference else "Booking completed",
    )
    if fee:
        LedgerEntry.objects.create(
            provider=provider,
            kind=EntryKind.PLATFORM_FEE,
            # Negative: the platform's share, already taken. Pending alongside the
            # earning, because the fee only becomes final when the earning does.
            amount=-fee,
            currency="INR",
            status=LedgerEntry.Status.PENDING,
            reference=booking_reference,
            description="BarberShop fee",
        )
    logger.info("Credited %s to %s for %s", fee, provider.display_name, booking_reference)


def _fee_for(gross: int) -> int:
    from django.conf import settings

    from core.money import compute_platform_fee

    return compute_platform_fee(gross, settings.PLATFORM_FEE_PERCENT)


@transaction.atomic
def debit(
    provider: ProviderProfile, *, kind: str, amount: int, reference: str = "", description: str = ""
) -> None:
    """Record money leaving the provider's balance.

    Used for a late-cancellation fee the platform keeps and for any adjustment
    agreed out of band. A payout goes through `record_payout`, which is stricter.
    """
    from payments.models import LedgerEntry

    LedgerEntry.objects.create(
        provider=provider,
        kind=kind,
        amount=-abs(amount),
        currency="INR",
        status=LedgerEntry.Status.CLEARED,
        reference=reference,
        description=description or kind.replace("_", " ").capitalize(),
    )


@transaction.atomic
def record_payout(
    provider: ProviderProfile,
    *,
    amount: int,
    reference: str,
    transfer_id: str = "",
    description: str = "",
) -> None:
    """Record money paid out to the provider's bank.

    Appends an entry rather than decrementing a balance, which is what makes the
    history auditable.

    ``reference`` is *our* reference for the withdrawal, not the gateway's
    transfer id: the settlement callback looks the entry up by it, and a gateway
    id that arrives with the response is not necessarily the one on the way
    back.
    """
    from payments.models import LedgerEntry

    LedgerEntry.objects.create(
        provider=provider,
        kind=EntryKind.PAYOUT,
        # Negative, like every other debit. Sign conventions are the whole
        # reason the balance is derivable.
        amount=-abs(amount),
        currency="INR",
        status=LedgerEntry.Status.PAID_OUT,
        reference=reference,
        description=description or (f"Withdrawal {transfer_id}" if transfer_id else "Withdrawal"),
    )
    logger.info("Paid out %s to %s (%s)", amount, provider.display_name, reference)
