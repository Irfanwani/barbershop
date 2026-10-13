"""What an appointment costs, in one place.

There are now two ways an appointment comes into existence: a customer books
one, and a recurring series books the next one. They **must** price identically,
or a customer discovers at week three of a series that it costs something
different from what they agreed to at week zero.

So the money lives here, once. Both callers pass in the services and any
discount and get back the same numbers, computed by the same functions, in the
same order.

The order is fixed and is the whole point of :func:`promotions.models.price`:
**a promo code comes off first, then points.** Anything that computes a total
itself will eventually get that order wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from bookings.models import BookingStatus
from core.money import CURRENCY, compute_deposit
from promotions.models import PriceBreakdown, PromoCode, price


@dataclass(frozen=True)
class AppointmentPrice:
    """Every number that has to agree, for one appointment."""

    subtotal: int
    platform_fee: int
    total: int
    discount: int
    #: Only the *points* part of the discount. Kept apart from ``discount``
    #: because points are recorded in the loyalty ledger, and the number that
    #: goes there is the points' worth, not the whole discount.
    points_discount: int
    deposit: int
    balance: int
    late_cancel_fee: int
    status: BookingStatus
    currency: str = CURRENCY


def price_appointment(
    provider,
    services,
    *,
    promo: PromoCode | None = None,
    points_off: int = 0,
) -> AppointmentPrice:
    """Price one appointment of these services at this shop.

    The deposit takes the **strictest** requirement across the basket rather
    than an average: a customer booking a colour service and a trim has agreed
    to the colour service's deposit, and averaging under-charges the shop on
    the thing that actually costs them the chair time.

    The late-cancellation fee is a slice of the deposit, worked out now. Both
    sides agree to it at booking time, so a shop tightening its policy next
    week must not change what somebody already agreed to pay.
    """
    subtotal = sum(service.price for service in services)
    breakdown: PriceBreakdown = price(subtotal, code=promo, points_off=points_off)

    deposit_percent = max((service.deposit_percent for service in services), default=0)
    deposit, balance = compute_deposit(breakdown.total, deposit_percent)
    late_cancel_fee, _ = compute_deposit(deposit, provider.late_cancel_fee_percent)

    status = (
        BookingStatus.AWAITING_CONFIRMATION
        if provider.requires_approval
        else BookingStatus.PENDING_PAYMENT
    )

    return AppointmentPrice(
        subtotal=subtotal,
        platform_fee=breakdown.platform_fee,
        total=breakdown.total,
        discount=breakdown.discount,
        points_discount=breakdown.points_discount,
        deposit=deposit,
        balance=balance,
        late_cancel_fee=late_cancel_fee,
        status=status,
    )


def booking_items(services) -> list[dict]:
    """The line items for these services, with their prices frozen in.

    Field dicts rather than unsaved rows, so a caller can attach them to any
    booking it is building: ``BookingItem(booking=booking, **fields)``.

    Snapshots rather than references: a shop renaming or repricing a service
    must not rewrite what a customer agreed to pay, or what they were told.
    """
    return [
        {
            "service": service,
            "name": service.name,
            "unit_price": service.price,
            "quantity": 1,
            "duration_minutes": service.duration_minutes,
        }
        for service in services
    ]


def duration_minutes(services) -> int:
    return sum(service.duration_minutes for service in services)
