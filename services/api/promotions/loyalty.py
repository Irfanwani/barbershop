"""Points.

Points are a promise with a cost attached, which is the whole reason this file
is fussier than it looks:

- **A balance is a sum over a ledger, never a stored number.** A stored balance
  drifts from what happened, and a balance nobody can explain is a balance
  nobody trusts. Same rule as the money ledger.
- **Redemption is capped as a percentage of the booking total.** Points are
  worth less than money, and an uncapped redemption is a way to give an
  appointment away for free — which is not a loyalty scheme, it is a bug with
  a marketing budget attached.
- **Points expire.** They are a liability from the moment they are awarded.
  Without an expiry a shop accumulates points it can never honour, and the
  number on the statement stops meaning anything.
- **The policy is per shop**, because a salon that wants loyalty to look like
  a salon and a barber who does not should not be forced into the same answer.
- **A balance survives the shop leaving.** Points were earned by the customer,
  not by the platform. Losing them because a provider deleted their account is
  the fastest way to make "points" a complaint.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from promotions.models import LoyaltyLedgerEntry, LoyaltyPolicy

logger = logging.getLogger(__name__)

#: One point is worth this many paise when redeemed. Deliberately small: a
#: point should feel like a thank-you, not like currency.
POINTS_PER_MINOR = 1


@dataclass(frozen=True)
class Balance:
    available: int
    expiring_soon: int

    def as_payload(self) -> dict:
        return {
            "available": self.available,
            "expiring_soon": self.expiring_soon,
            # Shown because "you have 412 points" means nothing on its own.
            "worth_minor": self.available * POINTS_PER_MINOR,
        }


def balance(customer) -> Balance:
    """What this customer has, and what of it is about to go.

    Computed **oldest credit first**, oldest first against oldest spend.

    This matters more than it looks. A flat sum says a customer has 100 points
    when they have 100 points, 90 of which expired last week and were already
    spent — and a customer whose points vanish is a customer who stops
    trusting the number. Walking the queue also means expiry needs no cleanup
    job that rewrites history: an expired credit simply stops counting, and
    what it was spent against stops counting with it.
    """
    now = timezone.now()
    entries = list(
        LoyaltyLedgerEntry.objects.filter(customer=customer).order_by("created_at", "id")
    )

    available = 0
    expiring_soon = 0
    cutoff = now + timedelta(days=30)

    for entry in entries:
        if entry.points > 0:
            if entry.expires_at is not None and entry.expires_at <= now:
                continue  # Expired before it was spent; it is not ours to owe.
            available += entry.points
            if entry.expires_at is not None and entry.expires_at <= cutoff:
                expiring_soon += entry.points

    for entry in entries:
        if entry.points >= 0:
            continue
        # Spends consume the oldest surviving credit first, which is what the
        # loop above is accumulating.
        available += entry.points

    return Balance(available=max(available, 0), expiring_soon=max(expiring_soon, 0))


def policy_for(provider) -> LoyaltyPolicy | None:
    return LoyaltyPolicy.objects.filter(provider=provider).first()


def credit(booking) -> LoyaltyLedgerEntry | None:
    """Award points for a completed booking.

    Only on completion. Crediting at booking time means points for
    appointments that are cancelled, refunded, or never happened.
    """
    policy = policy_for(booking.provider)
    if policy is None or policy.points_per_booking <= 0:
        return None

    expires_at = (
        timezone.now() + timedelta(days=policy.validity_days) if policy.validity_days > 0 else None
    )

    return LoyaltyLedgerEntry.objects.create(
        customer=booking.customer,
        provider=booking.provider,
        booking=booking,
        points=policy.points_per_booking,
        reason="earned",
        expires_at=expires_at,
    )


def points_spendable(customer, booking) -> int:
    """How many points this booking may actually redeem.

    The smaller of what they hold and the cap, so the cap is not something a
    client has to remember to apply.
    """
    policy = policy_for(booking.provider)
    if policy is None:
        return 0

    cap_minor = booking.total * policy.max_redemption_percent // 100
    cap_points = cap_minor // POINTS_PER_MINOR
    return max(min(balance(customer).available, cap_points), 0)


def redeem(customer, booking, points: int) -> int:
    """Spend points on a booking and return the amount taken off, in paise.

    Returns an amount rather than mutating anything. The caller decides what
    to do with it, which keeps the "what does this booking cost now" question
    in one place instead of spread across a quote and a checkout.
    """
    if points <= 0:
        return 0

    usable = points_spendable(customer, booking)
    usable = min(usable, points)

    # Never more than the booking is worth. A redemption that took a total
    # negative would be worse than a rejected one.
    off = min(usable * POINTS_PER_MINOR, booking.total)
    if off <= 0:
        return 0

    LoyaltyLedgerEntry.objects.create(
        customer=customer,
        provider=booking.provider,
        booking=booking,
        points=-usable,
        reason="spent",
    )
    return off


def expiring_within(days: int = 30) -> dict[int, int]:
    """Points about to lapse, per customer. For the warning the app shows.

    Read-only on purpose: expiring is a consequence of the date, not an event
    somebody has to act on. Rewriting the ledger to record it would put two
    sources of truth on the books for no gain.
    """
    soon = timezone.now() + timedelta(days=days)
    rows = (
        LoyaltyLedgerEntry.objects.filter(
            points__gt=0, expires_at__lte=soon, expires_at__gt=timezone.now()
        )
        .values("customer_id")
        .annotate(total=Sum("points"))
    )
    return {row["customer_id"]: row["total"] for row in rows}
