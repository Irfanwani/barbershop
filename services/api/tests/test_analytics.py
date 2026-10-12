"""The provider's numbers.

They were three figures summed on the device from the first page of the
bookings list — wrong past page one, wrong offline, and unable to answer "how
was last month" without paging backwards through every appointment in between.

The acceptance test for all of that is the same: **the numbers have to match
what the bookings list contains across every page, not the first.**
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from payments.ledger import credit_earning, credit_tip
from providers.models import WorkingHours
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
ANALYTICS = f"{V1}/providers/me/analytics/"

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def a_shop(*, open_every_day: bool = True):
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner, display_name="Sharp Cuts Studio")
    make_service(profile, name="Haircut", price=20000)

    if open_every_day:
        # Seven rows, so "available minutes" is a number and not zero.
        for weekday in range(7):
            WorkingHours.objects.create(
                provider=profile,
                weekday=weekday,
                is_closed=(weekday == 6),
                opens_at="09:00",
                closes_at="17:00",
            )
    return owner, profile


def a_booking(profile, *, days_ago: float, gross: int = 20000, status=BookingStatus.COMPLETED):

    ends_at = timezone.now() - timedelta(days=days_ago)
    booking = Booking.objects.create(
        customer=make_user(_next_name("cust")),
        provider=profile,
        starts_at=ends_at - timedelta(minutes=30),
        ends_at=ends_at,
        completed_at=ends_at if status == BookingStatus.COMPLETED else None,
        status=status,
        subtotal=gross,
        platform_fee=gross // 100,
        total=gross + gross // 100,
    )
    if status == BookingStatus.COMPLETED:
        credit_earning(profile, gross=gross, booking_reference=booking.reference)
    return booking


class TestTheWholeWindowNotOnePage:
    def test_a_booking_from_thirty_days_ago_is_counted(self):
        _owner, profile = a_shop()
        a_booking(profile, days_ago=29)

        response = _fetch(profile)

        assert response.data["current"]["bookings"] == 1

    def test_one_from_long_past_is_not(self):
        _owner, profile = a_shop()
        a_booking(profile, days_ago=45)

        response = _fetch(profile)

        assert response.data["current"]["bookings"] == 0

    def test_the_sum_covers_every_page_not_the_first(self):
        """The actual acceptance criterion.

        Thirty bookings across thirty days is two screens of a paged list. The
        device summed one of them.
        """
        _owner, profile = a_shop()
        # 1 to 29 days ago: day 30 is exactly on the window's edge, and
        # "the last thirty days" including both ends is thirty-one days.
        for day in range(1, 30):
            a_booking(profile, days_ago=day, gross=10000)

        response = _fetch(profile)

        assert response.data["current"]["bookings"] == 29
        assert response.data["current"]["revenue_earned"] == 290000 - 2900

    def test_it_does_not_need_the_bookings_list_at_all(self):
        """A dashboard that needs a network is not a dashboard."""
        _owner, profile = a_shop()
        a_booking(profile, days_ago=5, gross=50000)

        response = _fetch(profile)

        # 50000 gross less 1% is 49500.
        assert response.data["current"]["revenue_earned"] == 49500


class TestRevenue:
    def test_it_is_the_money_the_provider_keeps(self):
        _owner, profile = a_shop()
        a_booking(profile, days_ago=3, gross=20000)

        body = _fetch(profile).data["current"]

        assert body["revenue_earned"] == 19800
        assert body["platform_fees"] == 200

    def test_tips_count_and_are_not_fees(self):
        _owner, profile = a_shop()
        a_booking(profile, days_ago=3)
        credit_tip(profile, gross=5000, staff_name="Ravi")

        body = _fetch(profile).data["current"]

        assert body["tips"] == 5000
        assert body["revenue_earned"] == 19800 + 5000

    def test_an_uncashed_booking_is_not_revenue(self):
        """Credited on completion, because that is when it is earned."""
        _owner, profile = a_shop()
        a_booking(profile, days_ago=2, status=BookingStatus.CONFIRMED)

        body = _fetch(profile).data["current"]

        assert body["bookings"] == 1
        assert body["revenue_earned"] == 0


class TestRates:
    def test_no_show_rate_counts_only_appointments_that_had_their_day(self):
        """A cancellation is not a missed appointment."""
        _owner, profile = a_shop()
        a_booking(profile, days_ago=1)
        a_booking(profile, days_ago=2)
        a_booking(profile, days_ago=3, status=BookingStatus.NO_SHOW)
        a_booking(profile, days_ago=4, status=BookingStatus.CANCELLED_BY_CUSTOMER)

        body = _fetch(profile).data["current"]

        assert body["no_shows"] == 1
        assert body["cancelled"] == 1
        assert body["no_show_rate"] == 0.333

    def test_rebooking_counts_people_not_visits(self):
        """One regular with six visits is one customer."""

        _owner, profile = a_shop()
        regular = make_user(_next_name("regular"))

        for day in (10, 12, 14, 16, 18, 20):
            Booking.objects.create(
                customer=regular,
                provider=profile,
                starts_at=timezone.now() - timedelta(days=day + 1),
                ends_at=timezone.now() - timedelta(days=day),
                completed_at=timezone.now() - timedelta(days=day),
                status=BookingStatus.COMPLETED,
                subtotal=1000,
                platform_fee=10,
                total=1010,
            )

        body = _fetch(profile).data["current"]

        assert body["rebooking_rate"] == 0.0  # six visits, one person

    def test_somebody_who_came_back_counts(self):
        """The half of the rate that is not zero.

        Written deliberately: an earlier version of this excluded everyone who
        had been served in the window from the "came back" query, which is
        everyone, so the rate was permanently 0.0 and the test above alone
        would never have noticed.
        """
        _owner, profile = a_shop()
        for day in (10, 20):
            a_booking(profile, days_ago=day)  # two different customers
        regular = make_user(_next_name("returns"))
        Booking.objects.create(
            customer=regular,
            provider=profile,
            starts_at=timezone.now() - timedelta(days=25),
            ends_at=timezone.now() - timedelta(days=25),
            completed_at=timezone.now() - timedelta(days=25),
            status=BookingStatus.COMPLETED,
            subtotal=1000,
            platform_fee=10,
            total=1010,
        )
        # ...and is back tomorrow, inside the rebooking horizon.
        Booking.objects.create(
            customer=regular,
            provider=profile,
            starts_at=timezone.now() + timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=1),
            completed_at=timezone.now() + timedelta(days=1),
            status=BookingStatus.COMPLETED,
            subtotal=1000,
            platform_fee=10,
            total=1010,
        )

        body = _fetch(profile).data["current"]

        assert body["eligible_customers"] == 3
        assert body["rebooking_customers"] == 1
        assert body["rebooking_rate"] == 0.333

    def test_utilisation_is_booked_time_over_available_time(self):
        _owner, profile = a_shop()
        a_booking(profile, days_ago=1)

        body = _fetch(profile).data["current"]

        assert body["booked_minutes"] == 30
        # Six open days of eight hours, one chair, inside a 30-day window.
        assert body["available_minutes"] > 0
        assert 0 < body["utilisation"] < 1

    def test_no_data_is_zero_rather_than_a_gap(self):
        _owner, profile = a_shop()
        body = _fetch(profile).data["current"]

        assert body["rebooking_rate"] == 0.0
        assert body["no_show_rate"] == 0.0


class TestComparison:
    def test_the_previous_window_is_included(self):
        _owner, profile = a_shop()
        a_booking(profile, days_ago=5, gross=10000)
        a_booking(profile, days_ago=35, gross=10000)

        response = _fetch(profile)

        assert response.data["current"]["bookings"] == 1
        assert response.data["previous"]["bookings"] == 1

    def test_the_change_is_reported(self):
        _owner, profile = a_shop()
        for day in range(1, 4):
            a_booking(profile, days_ago=day, gross=10000)
        a_booking(profile, days_ago=35, gross=10000)

        change = _fetch(profile).data["changes"]["bookings"]

        assert change["now"] == 3
        assert change["before"] == 1
        assert change["difference"] == 2
        assert change["percent"] == 200.0

    def test_growth_from_nothing_is_not_a_percentage(self):
        """ "Up from nothing" is not a number, and rendering it as one is how a
        dashboard starts telling a shop its revenue tripled."""
        _owner, profile = a_shop()
        a_booking(profile, days_ago=3, gross=10000)

        change = _fetch(profile).data["changes"]["revenue_earned"]

        assert change["before"] == 0
        assert change["percent"] is None
        assert change["difference"] == 9900


class TestPerService:
    def test_it_is_ordered_by_what_each_service_earned(self):
        """A menu sorted A-Z is a menu, not an answer to "what goes on the
        front page"."""
        _owner, profile = a_shop()
        make_service(profile, name="Brow trim", price=5000)
        Booking.objects.create(
            customer=make_user(_next_name("c")),
            provider=profile,
            starts_at=timezone.now() - timedelta(days=2),
            ends_at=timezone.now() - timedelta(days=2),
            completed_at=timezone.now() - timedelta(days=2),
            status=BookingStatus.COMPLETED,
            subtotal=5000,
            platform_fee=50,
            total=5050,
        )
        a_booking(profile, days_ago=1, gross=40000)

        rows = _fetch(profile).data["current"]["per_service"]

        assert next(row["name"] for row in rows) != "Brow trim"
        assert rows[0]["earnings"] >= rows[-1]["earnings"]


class TestTheEndpoint:
    def test_a_window_outside_the_choices_is_refused(self):
        """Not silently coerced. `days=3650` should not become something else."""
        _owner, profile = a_shop()
        client, token = logged_in(profile.user)

        response = client.get(f"{ANALYTICS}?days=3650", **auth_header(token))

        assert response.status_code >= 400

    def test_the_offered_windows_are_listed(self):
        _owner, profile = a_shop()
        assert _fetch(profile).data["available_days"] == [7, 30, 90, 365]

    def test_each_offered_window_is_accepted(self):
        _owner, profile = a_shop()
        a_booking(profile, days_ago=3)

        for window_ in (7, 30, 90, 365):
            client, token = logged_in(profile.user)
            response = client.get(f"{ANALYTICS}?days={window_}", **auth_header(token))
            assert response.status_code == 200, window_
            assert response.data["current"]["bookings"] == 1

    def test_it_needs_a_provider_account(self):
        customer = make_user(_next_name("cust"))
        client, token = logged_in(customer)

        response = client.get(ANALYTICS, **auth_header(token))
        assert response.status_code in (403, 404)

    def test_a_customer_cannot_read_a_shops_numbers(self):
        _owner, _profile = a_shop()
        intruder = make_user(_next_name("nosy"))
        client, token = logged_in(intruder)

        response = client.get(ANALYTICS, **auth_header(token))
        assert response.status_code in (403, 404)


def _fetch(profile):
    client, token = logged_in(profile.user)
    response = client.get(ANALYTICS, **auth_header(token))
    assert response.status_code == 200, response.data
    return response
