"""Money handling.

Every amount in this project is an **integer number of the smallest unit** —
paise, not rupees. ``price = 25000`` means ₹250.00.

The old schema stored rupees in a ``PositiveIntegerField`` and had no concept of
currency at all. Integer paise means no float ever touches a price, so a total
can never come back as 2499.9999999.

The platform fee is computed in exactly one place — :func:`quote` — so there is
no second implementation to drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

CURRENCY = "INR"
MINOR_UNITS_PER_MAJOR = 100


def to_minor(major: float | str | Decimal) -> int:
    """Convert rupees to paise, rounding half up."""
    return int((Decimal(str(major)) * MINOR_UNITS_PER_MAJOR).quantize(Decimal("1")))


def to_major(minor: int) -> str:
    """Convert paise to a two-decimal rupee string, for display."""
    return f"{Decimal(minor) / MINOR_UNITS_PER_MAJOR:.2f}"


def format_minor(minor: int, currency: str = CURRENCY) -> str:
    symbol = {"INR": "₹"}.get(currency, f"{currency} ")
    return f"{symbol}{to_major(minor)}"


@dataclass(frozen=True, slots=True)
class QuoteLine:
    """One line of a price quote: what, for how much, at what unit price."""

    service_id: int
    name: str
    unit_price: int
    quantity: int = 1

    @property
    def line_total(self) -> int:
        return self.unit_price * self.quantity


@dataclass(frozen=True, slots=True)
class Quote:
    """The authoritative price of a booking, computed on the server.

    The client is shown this and asked to agree to it. A client that sends its
    own number is ignored — that was the hole in the old API.
    """

    lines: tuple[QuoteLine, ...]
    subtotal: int
    platform_fee: int
    total: int
    currency: str = CURRENCY
    duration_minutes: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "lines": [
                {
                    "service_id": line.service_id,
                    "name": line.name,
                    "unit_price": line.unit_price,
                    "quantity": line.quantity,
                    "line_total": line.line_total,
                }
                for line in self.lines
            ],
            "subtotal": self.subtotal,
            "platform_fee": self.platform_fee,
            "total": self.total,
            "duration_minutes": self.duration_minutes,
            "display": {
                "subtotal": format_minor(self.subtotal, self.currency),
                "platform_fee": format_minor(self.platform_fee, self.currency),
                "total": format_minor(self.total, self.currency),
            },
        }


def compute_platform_fee(subtotal: int, percent: int) -> int:
    """The platform's cut, rounded half up so it always sums cleanly.

    Rounding down on every line would let a customer shave a paise off each
    booking; rounding up would overcharge by a paise each time. Half-up is the
    only choice where ``fee + subtotal == total`` is stable.
    """
    if percent <= 0:
        return 0
    fee = (Decimal(subtotal) * Decimal(percent) / Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(fee)


def quote(
    services: list[tuple[int, str, int, int]],
    fee_percent: int,
    default_duration: int = 30,
) -> Quote:
    """Price a booking from authoritative service rows.

    ``services`` is a sequence of ``(service_id, name, unit_price, duration)``.
    Prices come from the database; nothing in here comes from the request body.
    """
    lines = tuple(
        QuoteLine(service_id=sid, name=name, unit_price=price, quantity=1)
        for sid, name, price, _duration in services
    )
    subtotal = sum(line.line_total for line in lines)
    platform_fee = compute_platform_fee(subtotal, fee_percent)
    duration = sum(duration or default_duration for *_r, duration in services)

    return Quote(
        lines=lines,
        subtotal=subtotal,
        platform_fee=platform_fee,
        total=subtotal + platform_fee,
        duration_minutes=duration,
    )
