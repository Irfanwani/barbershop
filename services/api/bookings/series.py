"""Turning a series into the appointments it owes.

The interesting rule is in :class:`~bookings.models.BookingSeries`: dates come
from an **origin**, not from the last thing that happened. This file exists to
make that concrete, and to be the one place that knows how an occurrence is
priced.

Two things this deliberately does not do:

- **It does not slide.** If week three cannot be created because the chair is
  taken, that week is skipped and week four still lands four weeks from the
  origin. Computing the next date from "the last one we managed" is the
  obvious implementation and it is wrong: a customer who missed February would
  find every later appointment moved a week earlier.
- **It does not price a series as a series.** Each occurrence is an ordinary
  booking with its own deposit, fee and cancellation policy, because it is
  separately chargeable. Promo codes and point redemptions are not carried
  forward: a code is spent once, and spending the customer's points without
  them present is not their decision to make for them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from bookings.models import (
    Booking,
    BookingItem,
    BookingSeries,
    SeriesStatus,
    has_room,
)
from bookings.pricing import booking_items, duration_minutes, price_appointment
from providers.models import Service, Staff

logger = logging.getLogger(__name__)

#: How far ahead occurrences are created. Enough that a customer opening the
#: app tomorrow sees next month already booked, without holding six weeks of
#: unpaid appointments against a shop's chair.
DEFAULT_HORIZON_DAYS = 21

#: A series nobody can keep. Six months of a shop turning up to an appointment
#: every four weeks is not loyalty, it is spam.
MAX_OCCURRENCES = 52

#: Matches the booking endpoint's limit. An occurrence can never be further out
#: than this, whichever direction the error came from.
MAX_BOOKING_HORIZON_DAYS = 90


@dataclass
class MaterialiseResult:
    created: int = 0
    skipped: list[str] = field(default_factory=list)
    finished: int = 0


def horizon_days() -> int:
    return int(getattr(settings, "SERIES_HORIZON_DAYS", DEFAULT_HORIZON_DAYS))


def create_series(
    *,
    customer,
    provider,
    services: list[Service],
    starts_at,
    interval_days: int,
    total_occurrences: int,
    staff=None,
    notes: str = "",
) -> tuple[BookingSeries, Booking]:
    """Book the first occurrence and record the rest as a series.

    The first appointment is created here, in the same transaction, rather than
    left for the scheduled task. A series whose first visit is four weeks away
    would otherwise be a promise with nothing behind it, and the customer would
    have no way to tell the difference between "booked" and "queued".
    """
    if not services:
        raise ValueError("A series needs at least one service.")
    if interval_days < 1:
        raise ValueError("A series needs an interval of at least a day.")
    if not 1 <= total_occurrences <= MAX_OCCURRENCES:
        raise ValueError(f"A series can have between 1 and {MAX_OCCURRENCES} visits.")

    with transaction.atomic():
        series = BookingSeries.objects.create(
            customer=customer,
            provider=provider,
            staff=staff,
            starts_at=starts_at,
            interval_days=interval_days,
            total_occurrences=total_occurrences,
        )
        booking = _create_occurrence(
            series=series,
            index=0,
            services=services,
            staff=staff,
            notes=notes,
        )
        if booking is None:
            # Nothing was written: the chair is taken on the very first date,
            # and a series that starts with a hole is not what anybody asked
            # for.
            raise ValueError("That slot is already taken. Pick another time.")
    return series, booking


def materialise(series: BookingSeries, *, now=None) -> Booking | None:
    """Create whatever occurrences are due. Returns the one created, if any."""
    if series.status != SeriesStatus.ACTIVE:
        return None

    moment = now or timezone.now()
    index = series.next_index(now=moment)
    if index is None:
        series.status = SeriesStatus.FINISHED
        series.save(update_fields=["status", "updated_at"])
        return None

    due_at = series.occurs_at(index)
    if due_at > moment + timedelta(days=horizon_days()):
        return None

    services = _services_for(series)
    if not services:
        # Every service on the series has been retired or deleted. Retiring
        # the series is kinder than leaving a task retrying it forever.
        series.status = SeriesStatus.STOPPED
        series.stopped_at = moment
        series.save(update_fields=["status", "stopped_at", "updated_at"])
        return None

    return _create_occurrence(series=series, index=index, services=services, staff=series.staff)


def materialise_due(*, now=None) -> MaterialiseResult:
    """Every active series whose next occurrence is due, once."""
    moment = now or timezone.now()
    cutoff = moment + timedelta(days=horizon_days())

    series_list = list(
        BookingSeries.objects.filter(status=SeriesStatus.ACTIVE, starts_at__lte=cutoff).order_by(
            "id"
        )
    )

    result = MaterialiseResult()
    for series in series_list:
        # Re-read: a series stopped between the query and here must not be
        # revived by a task that started before the stop landed.
        series.refresh_from_db()
        if series.status != SeriesStatus.ACTIVE:
            continue

        # One occurrence per run. Materialising several at once after downtime
        # would stack a backlog into a week of appointments in one go.
        booking = materialise(series, now=moment)
        if booking is None:
            reason = _why_not(series, moment)
            if reason:
                result.skipped.append(f"series {series.pk}: {reason}")
            missed = series.skipped_indices(now=moment)
            if missed:
                result.skipped.append(f"series {series.pk}: passed over occurrence(s) {missed}")
            if reason:
                continue
            series.refresh_from_db()
            if series.status == SeriesStatus.FINISHED:
                result.finished += 1
            continue
        result.created += 1

    logger.info("Series materialised: %s", result)
    return result


def _why_not(series: BookingSeries, now) -> str | None:
    """Why nothing was made, in words, for the log.

    "Not yet due" and "we could not book it" are different answers, and only
    the second is worth waking somebody up about.
    """
    index = series.next_index(now=now)
    if index is None:
        return None
    due_at = series.occurs_at(index)
    if due_at <= now + timedelta(days=horizon_days()):
        return f"no room at occurrence {index} ({due_at:%Y-%m-%d})"
    return None


def stop_series(series: BookingSeries, customer) -> BookingSeries:
    """The customer calls it off.

    Only stops the *future*. Appointments already created stay, because each
    one is separately chargeable and a customer who booked six weeks of trims
    is entitled to the ones they have already paid for.
    """
    series.status = SeriesStatus.STOPPED
    series.stopped_at = timezone.now()
    series.save(update_fields=["status", "stopped_at", "updated_at"])
    return series


def _services_for(series: BookingSeries) -> list[Service]:
    """The services this series books, from what is still on the menu.

    Read off the first occurrence's items rather than stored separately, so a
    series cannot end up booking something the customer never agreed to.
    """
    first = series.bookings.order_by("occurrence_index").first()
    if first is None:
        return []
    ids = [item.service_id for item in first.items.all() if item.service_id is not None]
    if not ids:
        return []
    # Reordered to match the original, because ``pk__in`` does not preserve it.
    # The customer chose an order, and a menu that reshuffles itself between
    # weeks reads as a different appointment.
    by_id = {service.pk: service for service in Service.objects.filter(pk__in=ids, is_active=True)}
    return [by_id[pk] for pk in ids if pk in by_id]


def _create_occurrence(
    *,
    series: BookingSeries,
    index: int,
    services: list[Service],
    staff: Staff | None,
    notes: str = "",
) -> Booking | None:
    """Write one appointment, or return ``None`` if the chair is taken."""
    starts_at = series.occurs_at(index)
    provider = series.provider

    # The same 90-day limit the booking endpoint enforces. It cannot bite while
    # the horizon is three weeks, but a shop whose task has been down for a
    # month must not wake up and book a customer a year ahead - the booking
    # that exists would be one the customer never asked for and cannot cancel.
    if starts_at > timezone.now() + timedelta(days=MAX_BOOKING_HORIZON_DAYS):
        logger.info("Occurrence %s of series %s is beyond the booking horizon", index, series.pk)
        return None

    ends_at = starts_at + timedelta(minutes=duration_minutes(services))

    # The same helper the customer-facing booking path uses. A series whose
    # later visits cost something different from the first is the bug this
    # function existing at all was meant to prevent.
    amounts = price_appointment(provider, services)

    with transaction.atomic():
        if not has_room(provider, starts_at, ends_at, staff=staff):
            return None

        try:
            booking = Booking.objects.create(
                customer=series.customer,
                provider=provider,
                staff=staff,
                starts_at=starts_at,
                ends_at=ends_at,
                subtotal=amounts.subtotal,
                platform_fee=amounts.platform_fee,
                total=amounts.total,
                deposit=amounts.deposit,
                balance=amounts.balance,
                cancellation_window_hours=provider.cancellation_window_hours,
                late_cancel_fee_percent=provider.late_cancel_fee_percent,
                late_cancel_fee=amounts.late_cancel_fee,
                currency=amounts.currency,
                status=amounts.status,
                notes=notes,
                series=series,
                occurrence_index=index,
            )
        except IntegrityError:
            # Another worker materialised this occurrence between the check and
            # the write. Its booking stands.
            logger.info("Occurrence %s of series %s already booked", index, series.pk)
            return None

        BookingItem.objects.bulk_create(
            [BookingItem(booking=booking, **fields) for fields in booking_items(services)]
        )

    logger.info("Booked occurrence %s of series %s", index, series.pk)
    return booking
