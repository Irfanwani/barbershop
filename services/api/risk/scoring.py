"""Scoring a customer's record, and deciding what to say about it.

The arithmetic is deliberately dull. The interesting decisions are the two
around it:

**When is there enough history to say anything?** A first no-show is a
perfectly ordinary thing. A customer whose first two appointments were both
no-shows is not, and a system that flags on the first one trains every provider
to ignore the flag. So nothing is said until there is a minimum sample, and a
customer with no history is treated as the safest thing they are: unknown.

**What happens when somebody is flagged?** A recommendation, and nothing else.
The quote says "we would suggest a deposit for this booking" and the price does
not move. A score that silently raises what somebody pays is a score that ends
in a chargeback, and the provider never sees the number that caused it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from observability import metrics
from risk.models import CustomerRisk, RiskFlag

logger = logging.getLogger(__name__)

#: Below this many finished appointments, say nothing. One no-show out of one
#: booking is a hundred per cent rate and means nothing at all.
MIN_SAMPLE = 3

#: The acceptance case is two no-shows in five, which is 40%. This line sits
#: below it so the case is comfortably inside "medium" rather than balanced on
#: the threshold - a score that flips on one booking is a score nobody acts on.
NO_SHOW_RATE_THRESHOLD = 0.25

#: Cancelling is much more common than not turning up, so the bar is higher.
CANCEL_RATE_THRESHOLD = 0.5

#: Words in a booking note that suggest somebody trying to move an appointment
#: off-platform. A small signal, and the reason it is a flag with a reason
#: attached rather than a silent score.
_SUSPICIOUS_PATTERNS = [
    r"\bmy number\b",
    r"\bcall me (?:on|at)\b",
    r"\bwhatsapp me\b",
    r"\btext me\b",
    r"\boutside (?:the )?(?:app|platform)\b",
    r"\bno need to (?:book|pay)\b",
    r"\bcash only\b",
]

#: Statuses that mean the appointment's day came and went, one way or another.
DECIDED = [
    BookingStatus.COMPLETED,
    BookingStatus.NO_SHOW,
    BookingStatus.CANCELLED_BY_CUSTOMER,
    BookingStatus.CANCELLED_BY_PROVIDER,
]


@dataclass(frozen=True)
class RiskAssessment:
    """What we know, and what we are willing to say about it."""

    total: int
    completed: int
    no_shows: int
    cancelled: int
    no_show_rate: float
    cancel_rate: float
    #: ``None`` means "not enough history to have an opinion".
    level: str | None
    suggested_deposit_percent: int | None
    flags: tuple[RiskFlag, ...]

    def as_payload(self) -> dict:
        return {
            "total_bookings": self.total,
            "completed": self.completed,
            "no_shows": self.no_shows,
            "cancelled": self.cancelled,
            "no_show_rate": round(self.no_show_rate, 3),
            "cancel_rate": round(self.cancel_rate, 3),
            "risk_level": self.level,
            # None, not 0: "we have no opinion" and "we think you are fine"
            # are different answers, and collapsing them loses the first.
            "suggested_deposit_percent": self.suggested_deposit_percent,
            "advisory": True,
            "flags": [
                {
                    # The id, because the one thing a provider can do about a
                    # flag is clear it, and that needs something to point at.
                    "id": flag_row.pk,
                    "kind": flag_row.kind,
                    "severity": flag_row.severity,
                    "reason": flag_row.reason,
                    "raised_at": flag_row.created_at,
                }
                for flag_row in self.flags
            ],
        }


def assess(customer, provider) -> RiskAssessment:
    """Work out where this customer stands at this shop.

    Reads ``Booking`` rows directly rather than a counter. At this volume a
    recount is cheaper than the bug where a stored total and the bookings
    disagree - and being wrong here means denying somebody an appointment they
    had every right to.
    """
    rows = list(
        Booking.objects.filter(customer=customer, provider=provider, status__in=DECIDED).only(
            "id", "status"
        )
    )

    total = len(rows)
    completed = sum(1 for row in rows if row.status == BookingStatus.COMPLETED)
    no_shows = sum(1 for row in rows if row.status == BookingStatus.NO_SHOW)
    cancelled = sum(
        1
        for row in rows
        if row.status in {BookingStatus.CANCELLED_BY_CUSTOMER, BookingStatus.CANCELLED_BY_PROVIDER}
    )

    # Cancelled by the *shop* is not the customer's doing. Counted for the
    # record, not held against them.
    cancelled_by_shop = sum(1 for row in rows if row.status == BookingStatus.CANCELLED_BY_PROVIDER)
    customer_cancelled = cancelled - cancelled_by_shop

    decisive = completed + no_shows
    no_show_rate = (no_shows / decisive) if decisive else 0.0
    cancel_rate = (customer_cancelled / total) if total else 0.0

    live_flags = tuple(
        RiskFlag.objects.filter(customer=customer, provider=provider, cleared_at__isnull=True)
    )

    level, suggested = _recommend(
        total=total, no_shows=no_shows, no_show_rate=no_show_rate, cancel_rate=cancel_rate
    )

    return RiskAssessment(
        total=total,
        completed=completed,
        no_shows=no_shows,
        cancelled=cancelled,
        no_show_rate=no_show_rate,
        cancel_rate=cancel_rate,
        level=level,
        suggested_deposit_percent=suggested,
        flags=live_flags,
    )


def _recommend(
    *, total: int, no_shows: int, no_show_rate: float, cancel_rate: float
) -> tuple[str | None, int | None]:
    """The recommendation: ``(level, suggested deposit percent)``.

    ``None`` for the level means there is not enough history to have an opinion.
    """
    if total < MIN_SAMPLE:
        # Unknown, not low. A shop that treats unknown as risky ends up
        # demanding deposits from everybody new.
        return None, None

    if no_shows >= 3 and no_show_rate >= 0.4:
        return "high", 100
    if no_show_rate >= NO_SHOW_RATE_THRESHOLD:
        return "medium", 50
    if cancel_rate >= CANCEL_RATE_THRESHOLD:
        # Cancelling is often a diary clash rather than disrespect. Worth
        # nudging towards a deposit, not a high-risk label.
        return "low", 25
    return None, None


def suggested_deposit_percent(provider, customer, *, default: int) -> int:
    """What deposit to *suggest*, for a provider to see.

    Advisory. The deposit actually taken is the service's own
    ``deposit_percent``, and this never changes it.
    """
    suggestion = assess(customer, provider).suggested_deposit_percent
    if suggestion is None:
        return default
    return max(suggestion, default)


def refresh(customer, provider) -> CustomerRisk:
    """Recompute and store the cached profile.

    A cache of the arithmetic, never the source of it.
    """
    result = assess(customer, provider)
    with transaction.atomic():
        profile, _created = CustomerRisk.objects.update_or_create(
            customer=customer,
            provider=provider,
            defaults={
                "total_bookings": result.total,
                "completed": result.completed,
                "no_shows": result.no_shows,
                "cancelled": result.cancelled,
                "computed_at": timezone.now(),
            },
        )
    return profile


def refresh_all() -> int:
    """Every pair that has bookings. Used by the nightly task."""
    from django.contrib.auth import get_user_model

    from providers.models import ProviderProfile

    pairs = set(
        Booking.objects.filter(status__in=DECIDED).values_list("customer_id", "provider_id")
    )
    if not pairs:
        return 0

    customers = {
        user.pk: user
        for user in get_user_model().objects.filter(pk__in={pair[0] for pair in pairs})
    }
    providers = {
        profile.pk: profile
        for profile in ProviderProfile.objects.filter(pk__in={pair[1] for pair in pairs})
    }

    count = 0
    for customer_id, provider_id in pairs:
        customer = customers.get(customer_id)
        provider = providers.get(provider_id)
        if customer is None or provider is None:
            continue
        refresh(customer, provider)
        count += 1
    logger.info("Refreshed %s risk profiles", count)
    return count


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def flag(customer, provider, *, kind: str, severity: str, reason: str) -> RiskFlag | None:
    """Raise a flag, or return the live one already there.

    A nightly task that runs every day must not produce a hundred identical
    flags for one person.
    """
    existing = RiskFlag.objects.filter(
        customer=customer, provider=provider, kind=kind, cleared_at__isnull=True
    ).first()
    if existing is not None:
        return existing

    try:
        with transaction.atomic():
            return RiskFlag.objects.create(
                customer=customer,
                provider=provider,
                kind=kind,
                severity=severity,
                reason=reason,
            )
    except Exception:
        return RiskFlag.objects.filter(
            customer=customer, provider=provider, kind=kind, cleared_at__isnull=True
        ).first()


def clear(flag_row: RiskFlag, *, by) -> RiskFlag:
    """Let somebody past a bad month.

    Without this a flag that was once true is true forever, and a customer who
    fixed whatever it was has no way of showing that.
    """
    flag_row.cleared_at = timezone.now()
    flag_row.cleared_by = by
    flag_row.save(update_fields=["cleared_at", "cleared_by", "updated_at"])
    return flag_row


def sweep_for_flags(*, window_days: int = 30, lookback_days: int = 90) -> int:
    """Look for the three patterns worth a person's attention.

    All of them are *flags*, not bans. Mass cancelling is usually a diary
    clash, and one bad no-show run is usually a bad month - which is exactly
    why somebody gets to look before anything changes.
    """
    from datetime import timedelta

    from django.contrib.auth import get_user_model

    from providers.models import ProviderProfile

    since = timezone.now() - timedelta(days=window_days)
    lookback = timezone.now() - timedelta(days=lookback_days)
    raised = 0

    def _customer(customer_id: int):
        return get_user_model().objects.filter(pk=customer_id).first()

    def _provider(provider_id: int):
        return ProviderProfile.objects.filter(pk=provider_id).first()

    # 1. Somebody churning slots: repeatedly booking and cancelling or missing,
    #    with almost nothing else on the books.
    churned = (
        Booking.objects.filter(
            status__in=[BookingStatus.CANCELLED_BY_CUSTOMER, BookingStatus.NO_SHOW],
            created_at__gte=since,
        )
        .values_list("customer_id", "provider_id")
        .distinct()
    )
    for customer_id, provider_id in churned:
        recent = Booking.objects.filter(
            customer_id=customer_id,
            provider_id=provider_id,
            created_at__gte=since,
            status__in=[BookingStatus.CANCELLED_BY_CUSTOMER, BookingStatus.NO_SHOW],
        ).count()
        total = Booking.objects.filter(
            customer_id=customer_id, provider_id=provider_id, created_at__gte=since
        ).count()
        if recent >= 3 and total <= recent + 1:
            customer, provider = _customer(customer_id), _provider(provider_id)
            if customer and provider:
                flag(
                    customer,
                    provider,
                    kind=RiskFlag.Kind.SERIAL_CANCELLER,
                    severity=RiskFlag.Severity.LOW,
                    reason=(
                        f"{recent} of {total} bookings cancelled or missed in the "
                        f"last {window_days} days"
                    ),
                )
                raised += 1

    # 2. Booking notes trying to arrange something off-platform.
    for booking in Booking.objects.filter(created_at__gte=lookback).exclude(notes=""):
        lowered = (booking.notes or "").lower()
        if not any(re.search(pattern, lowered) for pattern in _SUSPICIOUS_PATTERNS):
            continue
        customer, provider = _customer(booking.customer_id), _provider(booking.provider_id)
        if customer and provider:
            flag(
                customer,
                provider,
                kind=RiskFlag.Kind.SUSPICIOUS_NOTES,
                severity=RiskFlag.Severity.MEDIUM,
                reason="A booking note tried to arrange something off-platform",
            )
            raised += 1

    # 3. A repeat no-show is the one thing worth calling medium on its own.
    for customer_id, provider_id in (
        Booking.objects.filter(status=BookingStatus.NO_SHOW)
        .values_list("customer_id", "provider_id")
        .distinct()
    ):
        customer, provider = _customer(customer_id), _provider(provider_id)
        if customer is None or provider is None:
            continue
        result = assess(customer, provider)
        if result.no_shows >= 2 and result.no_show_rate >= 0.4:
            flag(
                customer,
                provider,
                kind=RiskFlag.Kind.REPEAT_NO_SHOW,
                severity=RiskFlag.Severity.MEDIUM,
                reason=(
                    f"{result.no_shows} no-shows out of "
                    f"{result.completed + result.no_shows} appointments"
                ),
            )
            raised += 1

    # 4. No-show outcomes, counted while the sweep already has them in hand.
    #
    # The counter is per provider so a no-show problem confined to one shop is
    # distinguishable from a platform-wide one. Recomputed from the bookings
    # table on every request anyway, so this is a signal rather than a record.
    for provider_id, no_shows, ended in (
        Booking.objects.filter(status__in=[BookingStatus.COMPLETED, BookingStatus.NO_SHOW])
        .values("provider_id")
        .annotate(
            no_shows=Count("pk", filter=Q(status=BookingStatus.NO_SHOW)),
            ended=Count("pk"),
        )
        .values_list("provider_id", "no_shows", "ended")
    ):
        if ended < 5:
            continue
        metrics.observe_no_show(provider_id=provider_id, no_show=no_shows / ended >= 0.5)

    logger.info("Raised %s risk flags", raised)
    return raised
