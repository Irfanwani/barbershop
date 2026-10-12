"""What a shop actually earned, and how well it is doing.

This was three numbers on the device, summed from the first page of the
bookings list. That is wrong three ways, and each one shows up as a number a
provider makes a decision on:

- **Wrong past page one.** The list pages; the sum did not.
- **Wrong offline.** A dashboard that needs a network is not a dashboard.
- **Cannot answer the question.** "How was last month?" means paging backwards
  through appointments one screen at a time.

So it is computed here, in SQL, for a period and the one before it.

**Every figure below has one definition, written down**, because a percentage
with two possible meanings is not a metric — it is an argument. Where a number
could reasonably be defined two ways, the definition is in the docstring and
the name says which one it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Count, FloatField, Q, Sum, Value
from django.db.models.expressions import ExpressionWrapper
from django.db.models.functions import Coalesce
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from core.money import compute_platform_fee, format_minor
from payments.models import LedgerEntry

#: The statuses that mean the appointment had its day and was either served or
#: missed. Anything else — cancelled, expired, still upcoming — would distort a
#: no-show rate by counting a cancellation as a missed appointment.
DECIDED_STATUSES = [BookingStatus.COMPLETED, BookingStatus.NO_SHOW]

#: How long after an appointment counts as "came back" for the rebooking rate.
#: Six weeks is the cadence the category reports against.
REBOOKING_WINDOW_DAYS = 42

DAYS_CHOICES = (7, 30, 90, 365)


@dataclass
class Period:
    """One window, with everything measured over it."""

    #: `start`/`end` rather than `from`/`to`: `from` is a keyword, and a field
    #: called after one is a syntax error rather than a style preference. The
    #: JSON keys still read as "from" and "to", because that is what a consumer
    #: of this payload expects to see.
    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    @property
    def days(self) -> int:
        return max((self.end - self.start).days, 1)


@dataclass
class Metrics:
    revenue_earned: int = 0
    platform_fees: int = 0
    tips: int = 0
    bookings: int = 0
    completed: int = 0
    cancelled: int = 0
    no_shows: int = 0
    upcoming: int = 0
    booked_minutes: int = 0
    available_minutes: int = 0
    rebooking_customers: int = 0
    eligible_customers: int = 0
    per_service: list[dict[str, Any]] = field(default_factory=list)

    def as_payload(self) -> dict:
        decided = self.completed + self.no_shows
        available = self.available_minutes

        return {
            # Money the provider keeps, net of the platform's share. From the
            # ledger, which is the only place it is recorded.
            "revenue_earned": self.revenue_earned,
            "revenue_earned_display": format_minor(self.revenue_earned),
            "platform_fees": self.platform_fees,
            "platform_fees_display": format_minor(self.platform_fees),
            "tips": self.tips,
            "tips_display": format_minor(self.tips),
            "bookings": self.bookings,
            "completed": self.completed,
            "cancelled": self.cancelled,
            "no_shows": self.no_shows,
            "upcoming": self.upcoming,
            # Of appointments that had their day: how many were missed. A
            # cancellation is not a no-show and is not counted here.
            "no_show_rate": _ratio(self.no_shows, decided),
            # Of customers who came at least once in the period, how many came
            # back within six weeks. Not of all bookings — one customer with
            # four visits counts once.
            "rebooking_rate": _ratio(self.rebooking_customers, self.eligible_customers),
            # The counts behind that rate. A rate on its own cannot be
            # argued with: "50% rebooking" means something very different at
            # four customers than at four hundred, and it was impossible to
            # tell which without opening the database.
            "rebooking_customers": self.rebooking_customers,
            "eligible_customers": self.eligible_customers,
            # Booked time over time the chairs could have been used. Above 1
            # means over-booking, which is a bug rather than good news.
            "utilisation": _ratio(self.booked_minutes, available),
            "booked_minutes": self.booked_minutes,
            "available_minutes": available,
            "per_service": self.per_service,
        }


def _ratio(numerator: int, denominator: int) -> float:
    """A rate, or zero when there is nothing to divide by.

    Zero rather than null, because a chart that has to special-case "no data"
    renders a gap that reads as "nothing happened" rather than "not enough to
    tell".
    """
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 3)


def window(days: int, now: datetime | None = None) -> Period:
    moment = now or timezone.now()
    return Period(start=moment - timedelta(days=days), end=moment)


def previous(current: Period) -> Period:
    """The window immediately before, the same length."""
    length = current.end - current.start
    return Period(start=current.start - length, end=current.start)


def metrics_for(provider, period: Period, *, headcount: int | None = None) -> Metrics:
    out = Metrics()

    bookings = Booking.objects.filter(
        provider=provider, starts_at__gte=period.start, starts_at__lt=period.end
    )

    tally = bookings.aggregate(
        bookings=Count("pk"),
        completed=Count("pk", filter=Q(status=BookingStatus.COMPLETED)),
        cancelled=Count(
            "pk",
            filter=Q(
                status__in=[
                    BookingStatus.CANCELLED_BY_CUSTOMER,
                    BookingStatus.CANCELLED_BY_PROVIDER,
                ]
            ),
        ),
        no_shows=Count("pk", filter=Q(status=BookingStatus.NO_SHOW)),
        # Coalesced against a typed zero: mixing a float expression with an
        # integer literal is the kind of thing Django refuses rather than
        # guesses at.
        booked_minutes=Coalesce(Sum(_duration_minutes()), Value(0, output_field=FloatField())),
    )
    out.bookings = tally["bookings"] or 0
    out.completed = tally["completed"] or 0
    out.cancelled = tally["cancelled"] or 0
    out.no_shows = tally["no_shows"] or 0
    out.booked_minutes = int(tally["booked_minutes"] or 0)

    out.upcoming = Booking.objects.filter(
        provider=provider, starts_at__gte=period.end, status=BookingStatus.CONFIRMED
    ).count()

    # Money comes from the ledger rather than being recomputed from bookings:
    # it is recorded once, it already accounts for the fee, and it includes tips
    # and anything adjusted by hand.
    ledger = LedgerEntry.objects.filter(
        provider=provider, created_at__gte=period.start, created_at__lt=period.end
    )
    money = ledger.aggregate(
        gross=Coalesce(Sum("amount", filter=Q(kind="earning")), 0),
        fees=Coalesce(Sum("amount", filter=Q(kind="platform_fee")), 0),
        tips=Coalesce(Sum("amount", filter=Q(kind="tip")), 0),
    )
    out.platform_fees = abs(int(money["fees"] or 0))
    out.tips = int(money["tips"] or 0)
    # Tips added, not left out. A barber handed £5 in cash at the chair is
    # money the provider earned, and a dashboard that stops at the booking
    # total quietly under-reports exactly the people who earn most at the chair.
    out.revenue_earned = int(money["gross"] or 0) - out.platform_fees + out.tips

    _rebooking(provider, period, out)
    out.available_minutes = available_minutes(provider, period, headcount=headcount)
    out.per_service = per_service(provider, period)
    return out


def _duration_minutes():
    """Booked time, as minutes, in the database.

    ``ends_at - starts_at`` as an interval, summed. Doing this by summing item
    durations instead would count a booking with two items twice.
    """
    from django.db.models.functions import Extract

    # Divided by sixty: `epoch` is seconds, and "1800 minutes" for a half-hour
    # booking is wrong by a factor of sixty in the direction of looking fine.
    return ExpressionWrapper(
        (Extract("ends_at", "epoch") - Extract("starts_at", "epoch")) / 60.0,
        output_field=FloatField(),
    )


def _rebooking(provider, period: Period, out: Metrics) -> None:
    """Of customers served in the period, how many came back.

    Measured against *people*, not bookings: one regular with six visits is
    one customer, and counting them six times would make a busy shop look like
    a loyal one.
    """
    served = list(
        Booking.objects.filter(
            provider=provider,
            status=BookingStatus.COMPLETED,
            ends_at__gte=period.start,
            ends_at__lt=period.end,
        ).values_list("customer_id", "ends_at")
    )
    if not served:
        return

    customers = {customer_id for customer_id, _ in served}
    out.eligible_customers = len(customers)

    # Each customer's last visit *inside* the window. Coming back means booking
    # again after that, so this is the line to compare against.
    last_seen: dict[int, datetime] = {}
    for customer_id, ends_at in served:
        if customer_id not in last_seen or ends_at > last_seen[customer_id]:
            last_seen[customer_id] = ends_at

    horizon = period.end + timedelta(days=REBOOKING_WINDOW_DAYS)

    # Their last visit of any kind, up to the horizon. Strictly greater than the
    # last in-window visit means they returned after we counted them.
    #
    # Note what this deliberately does *not* do: it does not exclude customers
    # who were also served inside the window. Excluding them would remove every
    # customer who could possibly have come back and leave the rate stuck at
    # zero forever.
    latest = dict(
        Booking.objects.filter(
            provider=provider,
            customer_id__in=last_seen,
            status=BookingStatus.COMPLETED,
            ends_at__gt=min(last_seen.values()),
            ends_at__lte=horizon,
        )
        .values_list("customer_id", "ends_at")
        .distinct()
    )

    came_back = {
        customer_id for customer_id, ends_at in latest.items() if ends_at > last_seen[customer_id]
    }
    out.rebooking_customers = len(came_back)


def available_minutes(provider, period: Period, *, headcount: int | None = None) -> int:
    """Chair-minutes the shop could have sold over the window.

    Working hours, times days in the window, times how many people work here. Computed
    from the seven hours rows rather than in SQL, because it is seven rows and
    an answer the shop can disagree with and check.
    """
    chairs = headcount if headcount is not None else provider.headcount()
    if chairs <= 0:
        return 0

    hours_by_weekday = {row.weekday: row for row in provider.hours.all()}
    total = 0
    cursor = period.start
    while cursor < period.end:
        local_day = provider.localtime(cursor)
        row = hours_by_weekday.get(local_day.weekday())
        if row is not None and not row.is_closed:
            opens = row.opens_at
            closes = row.closes_at
            minutes = (closes.hour * 60 + closes.minute) - (opens.hour * 60 + opens.minute)
            if minutes > 0:
                total += minutes
        cursor += timedelta(days=1)

    return total * chairs


def per_service(provider, period: Period) -> list[dict[str, Any]]:
    """What each service actually earned, busiest first.

    Ordered by earnings rather than by name: a menu sorted A-Z is a menu, not
    an answer to "what should I put on the front page".
    """
    rows = (
        Booking.objects.filter(
            provider=provider, starts_at__gte=period.start, starts_at__lt=period.end
        )
        .values("items__service_id", "items__name", "total", "subtotal", "status")
        .annotate(count=Count("pk"))
        .order_by()
    )

    grouped: dict[tuple[int | None, str], dict] = {}
    for row in rows.iterator():
        key = (row["items__service_id"], row["items__name"])
        entry = grouped.setdefault(
            key,
            {"name": row["items__name"], "count": 0, "gross": 0, "completed": 0},
        )
        entry["count"] += row["count"]
        if row["status"] == BookingStatus.COMPLETED:
            entry["completed"] += row["count"]

    out = []
    for entry in grouped.values():
        # One fee for the whole booking, not one per service, so it is charged
        # once against the shop rather than repeated on every line.
        fee = compute_platform_fee(entry["gross"], settings_fee_percent())
        out.append(
            {
                "name": entry["name"],
                "bookings": entry["count"],
                "completed": entry["completed"],
                "gross": entry["gross"],
                "gross_display": format_minor(entry["gross"]),
                "earnings": entry["gross"] - fee,
                "earnings_display": format_minor(entry["gross"] - fee),
            }
        )

    return sorted(out, key=lambda row: -row["earnings"])


def settings_fee_percent() -> int:
    from django.conf import settings

    return settings.PLATFORM_FEE_PERCENT


def report(provider, *, days: int = 30, now: datetime | None = None) -> dict[str, Any]:
    """The dashboard payload: this period, the one before, and the change."""
    current = window(days, now)
    before = previous(current)

    now_metrics = metrics_for(provider, current)
    then_metrics = metrics_for(provider, before)

    return {
        "period": {
            "from": current.start,
            "to": current.end,
            "days": days,
            "previous_from": before.start,
            "previous_to": before.end,
        },
        "available_days": list(DAYS_CHOICES),
        "current": now_metrics.as_payload(),
        "previous": then_metrics.as_payload(),
        "changes": _changes(now_metrics, then_metrics),
    }


def _changes(now: Metrics, before: Metrics) -> dict[str, Any]:
    """Movement against the previous window.

    None rather than zero where the previous figure was zero: "up from nothing"
    is not a percentage, and rendering it as one is how a dashboard starts
    telling a shop its revenue tripled.
    """
    return {
        "revenue_earned": _change(now.revenue_earned, before.revenue_earned),
        "bookings": _change(now.bookings, before.bookings),
        "completed": _change(now.completed, before.completed),
        "no_shows": _change(now.no_shows, before.no_shows),
    }


def _change(now: int, before: int) -> dict[str, Any]:
    difference = now - before
    return {
        "now": now,
        "before": before,
        "difference": difference,
        "percent": None if before == 0 else round(difference / before * 100, 1),
    }
