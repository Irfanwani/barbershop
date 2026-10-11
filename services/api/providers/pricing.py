"""Aggregated service pricing.

"What does a haircut cost around here?" is the question every customer asks
before they book, and the answer is not on any single shop's page. This
aggregates the prices shops are actually charging, so the app can say "typical
haircut is ₹250 to ₹400" instead of leaving the customer to scroll.

Two rules shape everything here:

* **Only real prices.** A service priced at ₹1 or ₹99999 is either a
  placeholder or a mistake, and averaging it in makes the median useless. Every
  figure is clamped to a plausible band before it counts.
* **Only enough shops to mean something.** A median across two shops is not a
  median, it is a coin flip. Where the sample is thin the response says so
  rather than pretending to a confidence it does not have.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count, QuerySet

from core.money import format_minor
from providers.models import Service

#: Prices outside this band are excluded. A shave is not ₹50 and not ₹50,000,
#: and one such row moves a median enough to mislead somebody choosing a shop.
MIN_PLAUSIBLE_PRICE = 500  # ₹5
MAX_PLAUSIBLE_PRICE = 500_000  # ₹5,000

#: Below this many shops, an aggregate is reported as thin rather than as fact.
MIN_SAMPLE_FOR_CONFIDENCE = 3


@dataclass
class PriceBand:
    """One row of the price picture: a percentile band and what sits under it."""

    service_type: str
    service_type_label: str
    sample_size: int
    minimum: int | None = None
    maximum: int | None = None
    average: int | None = None
    median: int | None = None
    p25: int | None = None
    p75: int | None = None
    #: Set when there are too few shops for the figures to mean much.
    is_thin: bool = False

    def as_dict(self) -> dict:
        return {
            "service_type": self.service_type,
            "service_type_label": self.service_type_label,
            "sample_size": self.sample_size,
            "minimum": self.minimum,
            "minimum_display": format_minor(self.minimum) if self.minimum else None,
            "maximum": self.maximum,
            "maximum_display": format_minor(self.maximum) if self.maximum else None,
            "average": self.average,
            "average_display": format_minor(self.average) if self.average else None,
            "median": self.median,
            "median_display": format_minor(self.median) if self.median else None,
            "p25": self.p25,
            "p25_display": format_minor(self.p25) if self.p25 else None,
            "p75": self.p75,
            "p75_display": format_minor(self.p75) if self.p75 else None,
            "is_thin": self.is_thin,
        }


def _percentile(sorted_values: list[int], fraction: float) -> int | None:
    """The value at ``fraction`` through a sorted list, nearest-rank.

    Nearest-rank rather than interpolation: the answer is always a price some
    shop actually charges, which is what makes it quotable to a customer.
    """
    if not sorted_values:
        return None
    index = round(fraction * (len(sorted_values) - 1))
    return sorted_values[index]


def _median(sorted_values: list[int]) -> int | None:
    if not sorted_values:
        return None
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return sorted_values[middle]
    # Average of the two middle values, rounded so the result is still a price
    # somebody charges rather than a fraction of one.
    return (sorted_values[middle - 1] + sorted_values[middle]) // 2


def plausible_prices(queryset: QuerySet[Service]) -> QuerySet[Service]:
    """The same queryset with implausible prices removed.

    Not `.filter(price__range=...)` on the caller's side: every caller needs it,
    and forgetting it in one place is how a nonsense row reaches a median.
    """
    return queryset.filter(
        is_active=True, price__gte=MIN_PLAUSIBLE_PRICE, price__lte=MAX_PLAUSIBLE_PRICE
    )


def price_band(
    service_type: str, service_type_label: str, queryset: QuerySet[Service]
) -> PriceBand:
    """Summarise what shops of one type are charging."""
    prices = list(plausible_prices(queryset).values_list("price", flat=True).order_by("price"))
    count = len(prices)

    if count == 0:
        return PriceBand(
            service_type=service_type,
            service_type_label=service_type_label,
            sample_size=0,
            is_thin=True,
        )

    return PriceBand(
        service_type=service_type,
        service_type_label=service_type_label,
        sample_size=count,
        minimum=prices[0],
        maximum=prices[-1],
        average=int(sum(prices) / count),
        median=_median(prices),
        p25=_percentile(prices, 0.25),
        p75=_percentile(prices, 0.75),
        is_thin=count < MIN_SAMPLE_FOR_CONFIDENCE,
    )


def service_name_bands(queryset: QuerySet[Service], *, limit: int = 10) -> list[dict]:
    """Typical prices for the most common service names.

    "Haircut" is comparable across shops; "Beard trim and scalp massage" is not.
    Only names several shops actually use produce a figure.
    """

    counts = (
        queryset.filter(is_active=True)
        .values("name")
        .annotate(providers=Count("provider", distinct=True))
        .filter(providers__gte=MIN_SAMPLE_FOR_CONFIDENCE)
        .order_by("-providers", "name")
    )

    bands: list[dict] = []
    for row in counts[:limit]:
        prices = list(
            plausible_prices(queryset.filter(name=row["name"]))
            .values_list("price", flat=True)
            .order_by("price")
        )
        if not prices:
            continue
        median = _median(prices)
        bands.append(
            {
                "name": row["name"],
                "sample_size": len(prices),
                "median": median,
                "median_display": format_minor(median) if median is not None else None,
                "minimum": prices[0],
                "minimum_display": format_minor(prices[0]),
                "maximum": prices[-1],
                "maximum_display": format_minor(prices[-1]),
            }
        )
    return bands
