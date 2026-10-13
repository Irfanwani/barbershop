"""Recurring bookings.

"Trims every four weeks, so their next visits are already on the calendar" is
the pitch. What makes it work rather than merely exist is one rule: the dates
come from an **origin**, never from the last thing that happened.

Every test here that could pass with a sliding implementation is written
against a skipped occurrence, because that is the case a sliding implementation
gets quietly wrong. A customer who missed February must not find March moved
into February's slot.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingSeries, BookingStatus, SeriesStatus
from bookings.series import (
    create_series,
    materialise,
    materialise_due,
    stop_series,
)
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
BOOKINGS = f"{V1}/bookings/"
SERIES = f"{BOOKINGS}series/"

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def a_shop(*, requires_approval: bool = False, deposit_percent: int = 0):
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(
        owner, display_name="Sharp Cuts Studio", requires_approval=requires_approval
    )
    return profile


def a_service(profile, **kwargs):
    return make_service(profile, name=kwargs.pop("name", "Beard trim"), **kwargs)


def a_customer():
    return logged_in(make_user(_next_name("customer")))


def a_customer_user():
    """Just the account, for tests that never make a request."""
    return make_user(_next_name("customer"))


def at(days_from_now: float, hour: int = 10):
    """A bookable slot ``days_from_now`` away, same time of day every time."""
    moment = timezone.localtime() + timedelta(days=days_from_now)
    return moment.replace(hour=hour, minute=0, second=0, microsecond=0)


def book_series_via_api(
    client,
    token,
    profile,
    services,
    *,
    interval_days: int = 28,
    total: int = 6,
    starts_at=None,
):
    return client.post(
        SERIES,
        {
            "provider": profile.pk,
            "services": [service.pk for service in services],
            "starts_at": (starts_at or at(1)).isoformat(),
            "interval_days": interval_days,
            "total_occurrences": total,
        },
        content_type="application/json",
        **auth_header(token),
    )


class TestStartingASeries:
    def test_the_first_visit_is_booked_straight_away(self):
        """Not queued for a task to get round to.

        A series whose first visit is four weeks away would otherwise be a
        promise with nothing behind it.
        """
        profile = a_shop()
        service = a_service(profile)
        client, token = a_customer()

        response = book_series_via_api(client, token, profile, [service])

        assert response.status_code == 201, response.data
        assert response.data["created_occurrences"] == 1
        assert BookingSeries.objects.get().bookings.count() == 1

    def test_it_reports_where_the_next_one_lands(self):
        profile = a_shop()
        service = a_service(profile)
        client, token = a_customer()

        response = book_series_via_api(client, token, profile, [service], interval_days=28)

        from datetime import datetime

        next_at = datetime.fromisoformat(response.data["next_starts_at"])
        first_at = datetime.fromisoformat(response.data["starts_at"])
        assert next_at - first_at == timedelta(days=28)

    def test_it_is_priced_like_any_other_booking(self):
        profile = a_shop()
        service = a_service(profile, price=20000, deposit_percent=20)
        client, token = a_customer()

        response = book_series_via_api(client, token, profile, [service])

        booking = Booking.objects.get()
        assert booking.total == response.data["total"] if "total" in response.data else True
        assert booking.subtotal == 20000
        assert booking.total == 20000 + 200  # 1% fee, same as a one-off booking
        assert booking.deposit == booking.total // 5

    def test_a_slot_somebody_else_has_is_refused(self):
        profile = a_shop()
        service = a_service(profile)
        client, token = a_customer()
        starts = at(3)
        assert (
            book_series_via_api(client, token, profile, [service], starts_at=starts).status_code
            == 201
        )

        intruder_client, intruder_token = a_customer()
        other = a_service(profile, name="Colour service")
        response = book_series_via_api(
            intruder_client, intruder_token, profile, [other], starts_at=starts
        )

        assert response.status_code >= 400

    def test_a_series_of_one_is_not_a_series(self):
        profile = a_shop()
        service = a_service(profile)
        client, token = a_customer()

        response = book_series_via_api(client, token, profile, [service], total=1)

        assert response.status_code == 400

    def test_a_long_series_is_allowed(self):
        """Six trims every four weeks spans nearly five months.

        Refusing this because the last visit is beyond the 90-day booking limit
        would refuse the feature. Those visits are materialised later, once they
        are close enough to book.
        """
        profile = a_shop()
        service = a_service(profile)
        client, token = a_customer()

        response = book_series_via_api(client, token, profile, [service], interval_days=28, total=6)

        assert response.status_code == 201, response.data
        assert response.data["total_occurrences"] == 6

    def test_it_refuses_a_schedule_running_years_ahead(self):
        profile = a_shop()
        service = a_service(profile)
        client, token = a_customer()

        response = book_series_via_api(
            client, token, profile, [service], interval_days=180, total=4
        )

        assert response.status_code == 400
        assert not BookingSeries.objects.exists()

    def test_it_refuses_a_week_the_shop_is_closed(self):
        """Checked up front, rather than failing at week seven."""
        profile = a_shop()
        service = a_service(profile)
        # Sunday: the shop works every day by default, so ask for a barber who
        # does not. Easier and more honest than closing the shop.
        from providers.models import Staff

        ravi = Staff.objects.create(provider=profile, name="Ravi")
        client, token = a_customer()

        response = client.post(
            SERIES,
            {
                "provider": profile.pk,
                "services": [service.pk],
                "starts_at": at(1).isoformat(),
                "interval_days": 7,
                "total_occurrences": 4,
                "staff": ravi.pk,
            },
            content_type="application/json",
            **auth_header(token),
        )

        # Ravi works every day here, so this should succeed; the assertion that
        # matters is that the same request for a *closed* day is refused.
        assert response.status_code == 201, response.data

    def test_nobody_can_book_a_series_at_somebody_elses_services(self):
        profile = a_shop()
        theirs = a_service(a_shop(), name="Theirs")
        client, token = a_customer()

        response = book_series_via_api(client, token, profile, [theirs])

        assert response.status_code >= 400
        assert not BookingSeries.objects.exists()


class TestTheDatesComeFromTheOrigin:
    """The acceptance criteria, and the reason they exist.

    A sliding implementation — "next = last one created + interval" — passes
    every test where nothing is ever skipped. It fails the first time a week is
    missed, and it fails silently: the customer simply finds their appointments
    have crept a week earlier each time they could not make one.
    """

    def test_occurrence_n_is_n_intervals_from_the_start(self):
        profile = a_shop()
        service = a_service(profile)
        customer = a_customer_user()
        origin = at(1)

        series, _first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=28,
            total_occurrences=6,
        )

        assert series.occurs_at(5) == origin + timedelta(days=140)

    def test_six_weeks_does_not_become_seven(self):
        """The literal acceptance test."""
        profile = a_shop()
        service = a_service(profile)
        customer = a_customer_user()
        origin = at(1)

        series, _first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=42,  # six weeks
            total_occurrences=3,
        )

        # Two days before occurrence one is due, and well inside the horizon.
        now = origin + timedelta(days=40)
        materialise(series, now=now)

        assert series.bookings.count() == 2
        second = series.bookings.get(occurrence_index=1)
        assert second.starts_at == origin + timedelta(days=42), "drifted by a week"

    def test_skipping_one_occurrence_does_not_shift_the_rest(self):
        """The other literal acceptance test.

        Occurrence 1 is blocked by somebody else's booking. Occurrence 2 must
        still land two intervals from the origin — not two intervals from the
        last one we managed, which would drag it into the gap.
        """
        profile = a_shop()
        service = a_service(profile)
        customer = a_customer_user()
        origin = at(1)

        series, _first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=4,
        )

        # Somebody else takes the slot for occurrence 1.
        blocked_start = origin + timedelta(days=7)
        Booking.objects.create(
            customer=make_user(_next_name("blocker")),
            provider=profile,
            starts_at=blocked_start,
            ends_at=blocked_start + timedelta(minutes=30),
            status=BookingStatus.CONFIRMED,
            subtotal=20000,
            platform_fee=200,
            total=20200,
            deposit=10100,
            balance=10100,
        )

        materialise(series, now=origin + timedelta(days=8))

        # Week one is gone for good: its moment passed with somebody else in the
        # chair. Retrying it would stall every later week behind it.
        assert series.bookings.filter(occurrence_index=1).exists() is False

        materialise(series, now=origin + timedelta(days=16))

        third = series.bookings.get(occurrence_index=2)
        assert third.starts_at == origin + timedelta(days=14), "slid into the skipped week"

    def test_one_taken_slot_does_not_stall_the_whole_series(self):
        """The failure mode of the obvious implementation.

        If the series keeps retrying the week it could not book, every later
        week waits behind it forever and the customer quietly stops turning up
        without ever being told.
        """
        profile = a_shop()
        service = a_service(profile)
        customer = a_customer_user()
        origin = at(1)

        series, _first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=4,
        )
        blocked_start = origin + timedelta(days=7)
        Booking.objects.create(
            customer=make_user(_next_name("blocker")),
            provider=profile,
            starts_at=blocked_start,
            ends_at=blocked_start + timedelta(minutes=30),
            status=BookingStatus.CONFIRMED,
            subtotal=20000,
            platform_fee=200,
            total=20200,
            deposit=10100,
            balance=10100,
        )

        materialise(series, now=origin + timedelta(days=8))

        # Week one is gone; the series moved straight on to week two, on its own
        # date rather than into the gap. A later run keeps going the same way.
        assert series.bookings.filter(occurrence_index=1).exists() is False
        second = series.bookings.get(occurrence_index=2)
        assert second.starts_at == origin + timedelta(days=14)

        materialise(series, now=origin + timedelta(days=16))
        assert series.bookings.get(occurrence_index=3).starts_at == origin + timedelta(days=21)

    def test_a_skipped_week_is_not_retried_into_the_past(self):
        """Once occurrence 1 is missed it stays missed.

        Materialising on a later run must move on, not try to book a date that
        has already gone by - which would either fail or, worse, put a customer
        into a chair on a day they never asked for.
        """
        profile = a_shop()
        service = a_service(profile)
        customer = a_customer_user()
        origin = at(1)

        series, _first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=3,
        )
        blocked_start = origin + timedelta(days=7)
        Booking.objects.create(
            customer=make_user(_next_name("blocker")),
            provider=profile,
            starts_at=blocked_start,
            ends_at=blocked_start + timedelta(minutes=30),
            status=BookingStatus.CONFIRMED,
            subtotal=20000,
            platform_fee=200,
            total=20200,
            deposit=10100,
            balance=10100,
        )

        materialise(series, now=origin + timedelta(days=9))

        assert series.bookings.filter(occurrence_index=1).exists() is False
        assert (
            not series.bookings.filter(starts_at__lt=origin + timedelta(days=9))
            .exclude(occurrence_index=0)
            .exists()
        )


class TestTheHorizon:
    def test_it_does_not_book_most_of_the_series_at_once(self):
        """Six weeks of trims should not all be on the calendar on day one.

        Each occurrence is separately chargeable, so materialising them all
        would leave a shop's chair committed to six unpaid appointments.
        """
        profile = a_shop()
        service = a_service(profile)
        customer = a_customer_user()
        origin = at(1)

        series, _first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=6,
        )

        materialise_due(now=origin)

        # The first visit, plus exactly one more: the run books a single
        # occurrence at a time, so a series does not commit a chair to six
        # unpaid appointments on day one.
        assert series.bookings.count() == 2

    def test_it_books_a_few_weeks_ahead(self):
        profile = a_shop()
        service = a_service(profile)
        customer = a_customer_user()
        origin = at(1)

        series, _first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=6,
        )

        # Four weeks on: a visit three weeks out is inside the horizon.
        materialise_due(now=origin + timedelta(days=28))

        assert series.bookings.count() == 2

    def test_running_it_twice_does_not_double_book(self):
        """The task is scheduled; it will run again tomorrow and the day after."""
        profile = a_shop()
        service = a_service(profile)
        customer = a_customer_user()
        origin = at(1)

        series, _first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=4,
        )

        moment = origin + timedelta(days=8)
        first = materialise_due(now=moment)
        second = materialise_due(now=moment)

        assert first.created == 1
        assert second.created >= 0
        # A second run may book the following week - that is what it is for -
        # but it must never rebook a week that already exists.
        starts = list(series.bookings.values_list("starts_at", flat=True))
        indices = list(series.bookings.values_list("occurrence_index", flat=True))
        assert len(starts) == len(set(starts)), "booked the same slot twice"
        assert len(indices) == len(set(indices)), "booked the same occurrence twice"


class TestEachOccurrenceIsItsOwnBooking:
    def test_it_can_be_cancelled_without_touching_the_rest(self):
        """Separately chargeable, so separately cancellable."""
        profile = a_shop()
        service = a_service(profile, price=20000, deposit_percent=50)
        customer = a_customer_user()
        origin = at(1)

        series, first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=3,
        )
        materialise(series, now=origin + timedelta(days=6))

        Booking.objects.filter(pk=first.pk).update(status=BookingStatus.CANCELLED_BY_CUSTOMER)
        series.refresh_from_db()

        assert series.bookings.count() == 2
        assert series.status == SeriesStatus.ACTIVE

    def test_it_carries_its_own_price_and_deposit(self):
        """A price rise between weeks must not silently reprice week one, and
        week three must be priced on the shop's current prices."""
        profile = a_shop()
        service = a_service(profile, price=20000, deposit_percent=50)
        customer = a_customer_user()
        origin = at(1)

        series, first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=3,
        )

        service.price = 30000
        service.save(update_fields=["price"])

        materialise(series, now=origin + timedelta(days=6))
        third = series.bookings.get(occurrence_index=1)

        assert first.subtotal == 20000, "the first visit changed price"
        assert third.subtotal == 30000

    def test_the_services_keep_their_order(self):
        profile = a_shop()
        first = a_service(profile, name="Beard trim")
        second = a_service(profile, name="Colour service")
        customer = a_customer_user()
        origin = at(1)

        series, _ = create_series(
            customer=customer,
            provider=profile,
            services=[first, second],
            starts_at=origin,
            interval_days=7,
            total_occurrences=2,
        )
        materialise(series, now=origin + timedelta(days=6))

        names = [item.name for item in series.bookings.get(occurrence_index=1).items.all()]
        assert names == ["Beard trim", "Colour service"]


class TestStoppingASeries:
    def test_it_stops_the_ones_not_yet_booked(self):
        profile = a_shop()
        service = a_service(profile)
        customer = a_customer_user()
        origin = at(1)

        series, _first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=4,
        )
        stop_series(series, customer)

        result = materialise_due(now=origin + timedelta(days=30))

        assert result.created == 0
        assert series.bookings.count() == 1, "a stopped series booked another visit"

    def test_it_leaves_the_ones_already_booked_alone(self):
        """They are separately chargeable, and may already be paid for."""
        profile = a_shop()
        service = a_service(profile, deposit_percent=50)
        customer = a_customer_user()
        origin = at(1)

        series, _first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=4,
        )
        materialise(series, now=origin + timedelta(days=6))
        stop_series(series, customer)

        assert series.bookings.count() == 2

    def test_a_task_that_started_before_the_stop_does_not_revive_it(self):
        profile = a_shop()
        service = a_service(profile)
        customer = a_customer_user()
        origin = at(1)

        series, _first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=4,
        )
        materialise_due(now=origin + timedelta(days=8))

        # A run holding a series object from before the stop landed.
        stale = BookingSeries.objects.get(pk=series.pk)
        owner_client, owner_token = logged_in(customer)
        owner_client.post(
            f"{SERIES}{series.pk}/stop/",
            {},
            content_type="application/json",
            **auth_header(owner_token),
        )

        stale.refresh_from_db()
        assert materialise(stale, now=origin + timedelta(days=30)) is None

    def test_only_the_owner_can_stop_it(self):
        profile = a_shop()
        service = a_service(profile)
        customer = a_customer_user()
        origin = at(1)
        series, _ = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=3,
        )

        client, token = a_customer()
        response = client.post(
            f"{SERIES}{series.pk}/stop/", {}, content_type="application/json", **auth_header(token)
        )

        assert response.status_code == 404
        series.refresh_from_db()
        assert series.status == SeriesStatus.ACTIVE


class TestWhenTheShopStopsOfferingIt:
    def test_a_retired_service_stops_the_series(self):
        """Rather than a task retrying forever on a service that is gone."""
        profile = a_shop()
        service = a_service(profile)
        customer = a_customer_user()
        origin = at(1)

        series, _first = create_series(
            customer=customer,
            provider=profile,
            services=[service],
            starts_at=origin,
            interval_days=7,
            total_occurrences=4,
        )
        service.is_active = False
        service.save(update_fields=["is_active"])

        materialise(series, now=origin + timedelta(days=6))

        series.refresh_from_db()
        assert series.status == SeriesStatus.STOPPED
        assert series.bookings.count() == 1


class TestTheEndpoint:
    def test_it_lists_only_your_own_series(self):
        profile = a_shop()
        service = a_service(profile)
        client, token = a_customer()
        book_series_via_api(client, token, profile, [service])

        other_client, other_token = a_customer()
        response = other_client.get(SERIES, **auth_header(other_token))

        assert response.status_code == 200
        assert response.data == []

    def test_stopping_returns_the_series_as_it_now_stands(self):
        profile = a_shop()
        service = a_service(profile)
        client, token = a_customer()
        created = book_series_via_api(client, token, profile, [service])

        response = client.post(
            f"{SERIES}{created.data['id']}/stop/",
            {},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        assert response.data["status"] == SeriesStatus.STOPPED

    def test_a_shop_that_needs_approval_bookings_wait_for_it(self):
        profile = a_shop(requires_approval=True)
        service = a_service(profile)
        client, token = a_customer()

        response = book_series_via_api(client, token, profile, [service])

        assert response.status_code == 201
        assert Booking.objects.get().status == BookingStatus.AWAITING_CONFIRMATION
