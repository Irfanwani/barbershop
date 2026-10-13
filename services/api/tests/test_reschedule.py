"""Moving a booking to a different time.

Rescheduling is not a cancel followed by a book. Cancelling loses the
reference the customer has been quoting, drops the reminders, breaks the
review link, and on a booking with a deposit already paid can charge them
twice. All of that for a change of hour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from payments.models import Payment, PaymentStatus
from tests.factories import (
    auth_header,
    logged_in,
    make_profile,
    make_provider_user,
    make_service,
    make_user,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


@dataclass
class Session:
    user: Any
    client: Any
    token: str

    @property
    def user_id(self) -> int:
        return self.user.pk

    def auth(self) -> dict:
        return auth_header(self.token)


def a_session(label: str) -> Session:
    user = make_user(_next_name(label))
    client, token = logged_in(user)
    return Session(user=user, client=client, token=token)


def in_days(days: int, hour: int = 10) -> datetime:
    day = timezone.localtime() + timedelta(days=days)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0)


def soon(minutes: int = 120) -> datetime:
    """The first bookable slot at least `minutes` away, inside working hours.

    `in_days(0)` reads as "today at ten", which is in the past for most of the
    day. Every test that wanted "a booking inside the late-cancellation window"
    was therefore written against a wall clock that only worked before ten in
    the morning - and failed for the rest of it, which is most of it.

    Anchored to the clock instead, and nudged forward to the next slot inside
    the shop's 09:00-20:00 so the booking is always bookable. Always within
    about twelve hours, so it is always inside the 24-hour window these tests
    are actually about.
    """
    moment = timezone.localtime() + timedelta(minutes=minutes)
    for _ in range(8):
        candidate = moment.replace(second=0, microsecond=0)
        # Thirty minutes is the fixture service's duration; it has to finish
        # before closing.
        if candidate.time() >= time(9, 0) and (candidate + timedelta(minutes=30)).time() <= time(
            20, 0
        ):
            return candidate
        moment = (candidate + timedelta(days=1)).replace(hour=9, minute=0)
    raise AssertionError("no bookable slot found within a week")


@dataclass
class Fixture:
    customer: Session
    provider_owner: Session
    profile: Any
    service: Any
    booking: Booking
    starts_at: datetime


def a_booking(
    days: int = 3, *, deposit: bool = False, starts_at: datetime | None = None
) -> Fixture:
    owner_user = make_provider_user(_next_name("shop"))
    client, token = logged_in(owner_user)
    provider = make_profile(owner_user, display_name="Sharp Cuts Studio")
    service = make_service(
        provider, price=20000, duration_minutes=30, deposit_percent=20 if deposit else 0
    )

    customer = a_session("customer")
    starts_at = starts_at if starts_at is not None else in_days(days)

    response = customer.client.post(
        f"{V1}/bookings/new/",
        {
            "provider": provider.pk,
            "services": [service.pk],
            "starts_at": starts_at.isoformat(),
        },
        **customer.auth(),
    )
    assert response.status_code == 201, response.data
    booking = Booking.objects.get(reference=response.data["reference"])

    return Fixture(
        customer=customer,
        provider_owner=Session(user=owner_user, client=client, token=token),
        profile=provider,
        service=service,
        booking=booking,
        starts_at=starts_at,
    )


def move(fixture: Fixture, starts_at: datetime, **body):
    return fixture.customer.client.post(
        f"{V1}/bookings/{fixture.booking.reference}/reschedule/",
        {"starts_at": starts_at.isoformat(), **body},
        **fixture.customer.auth(),
    )


class TestMoving:
    def test_the_booking_keeps_its_reference(self):
        fixture = a_booking()
        original = fixture.booking.reference

        response = move(fixture, in_days(4))

        assert response.status_code == 200, response.data
        assert response.data["reference"] == original
        assert Booking.objects.get(pk=fixture.booking.pk).reference == original

    def test_the_new_time_is_recorded(self):
        fixture = a_booking()
        target = in_days(4, hour=14)
        original_duration = fixture.booking.ends_at - fixture.booking.starts_at

        assert move(fixture, target).status_code == 200

        booking = Booking.objects.get(pk=fixture.booking.pk)
        assert booking.starts_at == target
        # The appointment does not get longer or shorter by moving.
        assert booking.ends_at - booking.starts_at == original_duration

    def test_the_price_is_unchanged_when_nothing_moved(self):
        fixture = a_booking()
        before = Booking.objects.get(pk=fixture.booking.pk).total

        assert move(fixture, in_days(4)).status_code == 200

        assert Booking.objects.get(pk=fixture.booking.pk).total == before

    def test_payments_survive_the_move(self):
        """The whole point: cancelling and rebooking would refund and re-charge."""
        fixture = a_booking(deposit=True)
        payment = Payment.objects.create(
            booking=fixture.booking,
            kind="deposit",
            amount=fixture.booking.deposit,
            currency="INR",
            status=PaymentStatus.CAPTURED,
        )
        captured = fixture.booking.amount_paid

        assert move(fixture, in_days(4)).status_code == 200

        booking = Booking.objects.get(pk=fixture.booking.pk)
        assert Payment.objects.filter(pk=payment.pk).exists()
        assert booking.amount_paid == captured

    def test_reminders_follow_the_booking(self):
        """They are rebuilt from the booking, so nothing can go out at the old hour."""
        fixture = a_booking()
        target = in_days(4, hour=14)

        move(fixture, target)

        booking = Booking.objects.get(pk=fixture.booking.pk)
        assert booking.starts_at == target
        assert booking.minutes_until_start() > 0

    def test_the_provider_can_move_it_too(self):
        fixture = a_booking()
        response = fixture.provider_owner.client.post(
            f"{V1}/bookings/{fixture.booking.reference}/reschedule/",
            {"starts_at": in_days(4).isoformat()},
            **fixture.provider_owner.auth(),
        )
        assert response.status_code == 200

    def test_a_stranger_cannot_move_it(self):
        fixture = a_booking()
        stranger = a_session("stranger")

        response = stranger.client.post(
            f"{V1}/bookings/{fixture.booking.reference}/reschedule/",
            {"starts_at": in_days(4).isoformat()},
            **stranger.auth(),
        )
        assert response.status_code == 404


class TestRefusals:
    def test_moving_onto_a_booked_slot_is_refused(self):
        fixture = a_booking(days=3)
        target = in_days(3, hour=11)

        # Somebody else takes the slot we are trying to move into.
        rival = a_session("rival")
        response = rival.client.post(
            f"{V1}/bookings/new/",
            {
                "provider": fixture.profile.pk,
                "services": [fixture.service.pk],
                "starts_at": target.isoformat(),
            },
            **rival.auth(),
        )
        assert response.status_code == 201, response.data

        refused = move(fixture, target)
        assert refused.status_code >= 400
        assert Booking.objects.get(pk=fixture.booking.pk).starts_at == fixture.starts_at

    def test_moving_outside_working_hours_is_refused(self):
        fixture = a_booking()
        response = move(fixture, in_days(4, hour=3))

        assert response.status_code >= 400
        assert "open" in str(response.data).lower()

    def test_moving_into_the_past_is_refused(self):
        fixture = a_booking()
        response = move(fixture, in_days(-1))

        assert response.status_code >= 400

    def test_a_cancelled_booking_cannot_be_moved(self):
        fixture = a_booking()
        Booking.objects.filter(pk=fixture.booking.pk).update(
            status=BookingStatus.CANCELLED_BY_CUSTOMER
        )
        fixture.booking.refresh_from_db()

        response = move(fixture, in_days(4))
        assert response.status_code >= 400

    def test_a_service_the_shop_dropped_cannot_be_silently_moved(self):
        fixture = a_booking()
        fixture.service.is_active = False
        fixture.service.save(update_fields=["is_active"])

        response = move(fixture, in_days(4))

        assert response.status_code >= 400
        assert "no longer offers" in str(response.data)


class TestPriceChanges:
    def test_a_changed_price_stops_the_move_and_reports_both_numbers(self):
        fixture = a_booking()
        before = Booking.objects.get(pk=fixture.booking.pk).total

        fixture.service.price = 30000
        fixture.service.save(update_fields=["price"])

        response = move(fixture, in_days(4))

        assert response.status_code == 409
        assert response.data["reason"] == "price_changed"
        assert response.data["old_total"] == before
        assert response.data["new_total"] > before
        assert Booking.objects.get(pk=fixture.booking.pk).starts_at == fixture.starts_at

    def test_the_move_proceeds_once_the_change_is_accepted(self):
        fixture = a_booking()
        fixture.service.price = 30000
        fixture.service.save(update_fields=["price"])

        response = move(fixture, in_days(4), accept_price_change=True)

        assert response.status_code == 200, response.data
        booking = Booking.objects.get(pk=fixture.booking.pk)
        assert booking.total == response.data["total"]
        assert booking.subtotal == 30000

    def test_a_cheaper_price_also_stops_the_move(self):
        """Silently charging less is a shop eating a cost it agreed nowhere."""
        fixture = a_booking()
        fixture.service.price = 10000
        fixture.service.save(update_fields=["price"])

        response = move(fixture, in_days(4))

        assert response.status_code == 409
        assert response.data["difference"] < 0

    def test_the_deposit_split_moves_with_the_price(self):
        fixture = a_booking(deposit=True)
        fixture.service.price = 30000
        fixture.service.save(update_fields=["price"])

        move(fixture, in_days(4), accept_price_change=True)

        booking = Booking.objects.get(pk=fixture.booking.pk)
        # Still twenty per cent, of the new total.
        assert booking.deposit == booking.total // 5
        assert booking.deposit + booking.balance == booking.total


class TestTheCancellationWindowStillApplies:
    """These are about a booking that starts *inside* the 24-hour window.

    That cannot be expressed by arithmetic on the wall clock. `soon()` has to
    find a slot that is both inside working hours and less than 24 hours away,
    and those two constraints overlap only for part of the day: run at 02:00
    and the next slot inside opening hours is tomorrow morning, 31 hours out,
    which makes every one of these tests quietly assert the wrong thing.

    So the clock is fixed. Mid-morning, comfortably inside both.
    """

    @pytest.fixture(autouse=True)
    def a_fixed_clock(self):
        from freezegun import freeze_time

        with freeze_time("2026-06-01 10:00:00", tz_offset=0):
            yield

    def test_a_late_move_cancels_instead_of_moving(self):
        """Otherwise "I need a different time" dodges the late-cancel fee."""
        fixture = a_booking(starts_at=soon())
        original = fixture.booking.reference

        response = move(fixture, in_days(2))

        assert response.status_code == 200, response.data
        assert response.data["rescheduled"] is False
        assert response.data["cancelled"] is True

        booking = Booking.objects.get(reference=original)
        assert booking.status == BookingStatus.CANCELLED_BY_CUSTOMER
        assert booking.starts_at == fixture.starts_at

    def test_a_late_move_explains_why(self):
        fixture = a_booking(starts_at=soon())
        response = move(fixture, in_days(2))

        assert "cancellation window" in response.data["message"]

    def test_a_late_move_reports_the_fee_that_was_charged(self):
        fixture = a_booking(starts_at=soon(), deposit=True)
        expected = fixture.booking.late_cancel_fee

        response = move(fixture, in_days(2))

        assert response.data["late_cancel_fee"] == expected

    def test_an_early_move_is_allowed(self):
        fixture = a_booking(days=4)
        response = move(fixture, in_days(5))

        assert response.status_code == 200
        assert response.data["reference"] == fixture.booking.reference

    def test_a_provider_moving_a_late_booking_still_moves_it(self):
        """The fee only ever punishes the customer. The shop has the chair."""
        fixture = a_booking(starts_at=soon())
        response = fixture.provider_owner.client.post(
            f"{V1}/bookings/{fixture.booking.reference}/reschedule/",
            {"starts_at": in_days(2).isoformat()},
            **fixture.provider_owner.auth(),
        )

        assert response.status_code == 200, response.data
        assert (
            Booking.objects.get(pk=fixture.booking.pk).status != BookingStatus.CANCELLED_BY_CUSTOMER
        )
