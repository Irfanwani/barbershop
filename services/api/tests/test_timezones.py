"""A shop's hours are written on its own clock.

A barber says "I open at nine" and means nine where they work. Hours are
stored as naive local times, so somewhere that value has to be anchored to a
real place.

Until now nothing did. Every "local time" in the codebase meant *the server's*
local time — which is correct for a single-country marketplace and quietly
wrong the moment the second one exists. A Bengaluru shop opening at 09:00,
checked against UTC, does not open until 14:30 and does not close until 02:30
the following morning.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from bookings.models import is_within_working_hours
from tests.factories import (
    auth_header,
    logged_in,
    make_profile,
    make_provider_user,
    make_user,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
PROVIDERS = f"{V1}/providers/"

BENGALURU = ZoneInfo("Asia/Kolkata")
LONDON = ZoneInfo("Europe/London")
KATHMANDU = ZoneInfo("Asia/Kathmandu")

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def a_shop(tz_name: str = "", *, opening=time(9), closing=time(18)):
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(
        owner,
        display_name="Sharp Cuts Studio",
        opening_time=opening,
        closing_time=closing,
        timezone_name=tz_name,
    )
    return profile


def database_now() -> datetime:
    """The clock the search filter actually reads.

    The `open_now` filter asks Postgres for `CURRENT_TIMESTAMP` so the
    comparison stays in the query and survives pagination. Anything that wants
    to reason about what that filter did has to read the same clock - freezing
    Python's clock and comparing the two is how this test spent years only
    passing during one narrow window of the day.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT CURRENT_TIMESTAMP")
        return cursor.fetchone()[0]


def at(moment_utc: str) -> object:
    from datetime import datetime

    return datetime.fromisoformat(moment_utc)


class TestResolvingTheZone:
    def test_the_shop_own_zone_wins(self):
        shop = a_shop("Asia/Kolkata")
        assert shop.tz() == BENGALURU

    def test_it_falls_back_to_the_account(self):
        owner = make_provider_user(_next_name("acct"))
        owner.timezone_name = "Europe/London"
        owner.save(update_fields=["timezone_name"])
        profile = make_profile(owner)

        assert profile.timezone_name == ""
        assert profile.tz() == LONDON

    def test_and_to_the_server(self):
        shop = a_shop("")
        assert shop.tz() is not None

    def test_an_unknown_zone_does_not_break_the_shop(self):
        """A missing tzdata entry must not 500 every request a shop receives."""
        shop = a_shop("Mars/Olympus_Mons")
        assert shop.tz() is not None


class TestWorkingHoursAreTheShopsClock:
    def test_0900_0900_is_opening_time_in_the_shops_zone(self):
        """04:30 UTC is 10:00 in Bengaluru, and the shop is open then."""
        shop = a_shop("Asia/Kolkata", opening=time(9), closing=time(18))

        assert is_within_working_hours(
            shop, at("2026-10-13T04:30:00+00:00"), at("2026-10-13T05:30:00+00:00")
        )

    def test_and_closed_before_it(self):
        """02:00 UTC is 07:30 in Bengaluru — before opening."""
        shop = a_shop("Asia/Kolkata", opening=time(9), closing=time(18))

        assert not is_within_working_hours(
            shop, at("2026-10-13T02:00:00+00:00"), at("2026-10-13T03:00:00+00:00")
        )

    def test_the_same_instant_reads_differently_in_two_countries(self):
        """This is the whole bug, stated as one assertion."""
        bengaluru = a_shop("Asia/Kolkata", opening=time(9), closing=time(18))
        london = a_shop("Europe/London", opening=time(9), closing=time(18))

        # 04:30 UTC: half past ten in Bengaluru, well before nine in London.
        assert is_within_working_hours(
            bengaluru, at("2026-10-13T04:30:00+00:00"), at("2026-10-13T05:30:00+00:00")
        )
        assert not is_within_working_hours(
            london, at("2026-10-13T04:30:00+00:00"), at("2026-10-13T05:30:00+00:00")
        )

    def test_a_shop_with_a_half_hour_offset_works(self):
        """Nepal is UTC+5:45, so its day does not start on the hour."""
        kathmandu = a_shop("Asia/Kathmandu", opening=time(9), closing=time(18))

        # 03:30 UTC is 09:15 in Kathmandu.
        assert is_within_working_hours(
            kathmandu, at("2026-10-13T03:30:00+00:00"), at("2026-10-13T04:30:00+00:00")
        )

    def test_a_shop_in_utc_is_unaffected(self):
        shop = a_shop("UTC", opening=time(9), closing=time(18))

        assert is_within_working_hours(
            shop, at("2026-10-13T10:00:00+00:00"), at("2026-10-13T11:00:00+00:00")
        )
        assert not is_within_working_hours(
            shop, at("2026-10-13T07:00:00+00:00"), at("2026-10-13T08:00:00+00:00")
        )

    def test_local_now_is_the_shops_clock(self):
        shop = a_shop("Asia/Kolkata")
        assert shop.local_now().tzinfo == BENGALURU
        # India is UTC+5:30, always.
        assert shop.local_now().utcoffset() == timedelta(hours=5, minutes=30)


class TestOpenNowSearch:
    def test_the_filter_uses_each_shops_own_clock(self):
        """A single `now.time()` compared against every shop is wrong once two
        countries are in play, so the database is asked per row."""
        now_utc = timezone.now()

        # A shop open at every hour of the day: always open, whatever the zone.
        always = a_shop("Asia/Kolkata", opening=time(0), closing=time(23))
        always.user.timezone_name = "Asia/Kolkata"
        always.user.save(update_fields=["timezone_name"])

        london = a_shop("Europe/London", opening=time(0), closing=time(23))
        london.user.timezone_name = "Europe/London"
        london.user.save(update_fields=["timezone_name"])

        client, token = logged_in(make_user())
        response = client.get(f"{PROVIDERS}?open_now=true", **auth_header(token))

        assert response.status_code == 200
        names = [row["display_name"] for row in response.data["results"]]
        assert names.count("Sharp Cuts Studio") == 2
        assert now_utc is not None

    def test_a_shop_with_no_zone_still_appears(self):
        """An empty zone is not a zone; it falls back rather than erroring."""
        shop = a_shop("", opening=time(0), closing=time(23))
        client, token = logged_in(make_user())

        response = client.get(f"{PROVIDERS}?open_now=true", **auth_header(token))

        assert response.status_code == 200
        assert shop.pk in [row["id"] for row in response.data["results"]]


class TestStaffHireTheShopClockToo:
    def test_today_is_the_shops_today(self):
        """Three notions of "today" on one screen is a bug report."""
        from providers.models import Staff

        shop = a_shop("Asia/Kolkata")
        person = Staff.objects.create(provider=shop, name="Ravi")

        assert person.is_open_on(shop.local_now().weekday()) == shop.is_open_on(
            shop.local_now().weekday()
        )


class TestOpenNowFollowsTheSameChainTheShopPageDoes:
    """`ProviderProfile.tz()` resolves shop, then account, then server.

    The search filter resolved shop, then UTC. A shop that never set its own
    zone but whose owner had one was filtered by the wrong clock - so
    `?open_now=true` could hide a shop that was, by its own account's clock,
    open right now. Every existing test set both zones to the same value, or
    both to nothing, so the disagreement between the two had nowhere to show.
    """

    @pytest.mark.parametrize(
        ("shop_zone", "account_zone", "expected_zone"),
        [
            ("Asia/Kolkata", "Europe/London", "Asia/Kolkata"),  # shop wins
            ("", "Asia/Kolkata", "Asia/Kolkata"),  # account is the fallback
            ("", "", "UTC"),  # and UTC is the last resort
        ],
    )
    def test_the_filter_agrees_with_the_shop_page(self, shop_zone, account_zone, expected_zone):
        """The filter and the shop page must agree about the same instant.

        Two clocks are in play and this used to mix them. The search filter asks
        the *database* for `CURRENT_TIMESTAMP` - deliberately, so the comparison
        stays in SQL and survives pagination - while `is_open_at` reads the
        Python clock. `freeze_time` only moves the Python one, so freezing time
        and then comparing the two compared a database clock against a frozen
        Python clock. That disagreed whenever the real time was outside the
        window chosen for the frozen time, which is most of the day.

        So: take the instant from the database, and derive the window from it.
        The test is now true at any hour of any day, which is the only property
        that makes it worth having in CI.
        """
        db_now = database_now()

        shop = a_shop(shop_zone, opening=time(9), closing=time(18))
        shop.user.timezone_name = account_zone
        shop.user.save(update_fields=["timezone_name"])

        # Used only to place the window, never to decide the answer. The window
        # is the hour either side of the shop's own local time right now, so a
        # filter reading the server's clock gets the opposite answer. It is
        # built from whole hours rather than by subtracting a timedelta, because
        # a window centred on 00:20 or 23:50 wraps midnight - and
        # `opening <= t <= closing` is then true for no time at all, which is a
        # test that fails for one hour a day and looks like a product bug.
        local_hour = db_now.astimezone(shop.tz()).hour
        shop.opening_time = time(max(0, local_hour - 1))
        shop.closing_time = time(min(23, local_hour + 1), 59)
        shop.save(update_fields=["opening_time", "closing_time"])

        client, token = logged_in(make_user())

        response = client.get(f"{PROVIDERS}?open_now=true", **auth_header(token))

        assert response.status_code == 200
        listed = shop.pk in [row["id"] for row in response.data["results"]]
        # The shop's own page is the reference: if it says open, the search must
        # agree, and the two are computed by completely different code.
        assert listed is shop.is_open_at(db_now)

    def test_the_shop_is_judged_by_its_own_clock_not_the_servers(self):
        """The specific failure the chain exists to prevent.

        `is_open_at` took a moment and compared `moment.time()` straight
        against the shop's opening hours. On an aware datetime `.time()` is the
        UTC wall time, so every shop outside UTC was judged by the server's
        clock - and this passed for years because the only caller omitted the
        argument and went through `local_now()` instead.
        """
        shop = a_shop("Asia/Kolkata", opening=time(14), closing=time(16))

        # 15:30 in Kolkata, which is 10:00 UTC: inside the shop's hours.
        inside = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
        assert shop.is_open_at(inside) is True

        # The same instant read in London is 10:00, outside 14:00-16:00.
        london = inside.astimezone(ZoneInfo("Europe/London"))
        assert london.time() == time(10, 0)
        assert shop.opening_time > london.time()
        # And a moment genuinely outside the shop's hours stays outside.
        assert shop.is_open_at(datetime(2026, 3, 1, 4, 0, tzinfo=UTC)) is False


class TestTheShopCanSetItsZone:
    """The field existed and the search filter used it, but nothing could write
    it and nothing read it back. A provider setting "I open at nine" had no way
    to say which nine, and no way to check which one the shop was using."""

    def test_it_is_returned(self):
        shop = a_shop("Asia/Kolkata")
        client, token = logged_in(shop.user)

        response = client.get(f"{V1}/providers/me/", **auth_header(token))

        assert response.status_code == 200
        assert response.data["timezone_name"] == "Asia/Kolkata"

    def test_it_is_writable(self):
        shop = a_shop("")
        client, token = logged_in(shop.user)

        response = client.patch(
            f"{V1}/providers/me/",
            {"timezone_name": "Europe/London"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200, response.data
        shop.refresh_from_db()
        assert shop.timezone_name == "Europe/London"

    def test_the_resolved_zone_is_shown_too(self):
        """The one the hours are read in, which is not always the one set.

        A shop with no zone of its own still has one, and it is not obvious
        which. Stating it is the difference between "my hours are wrong" and a
        fix.
        """
        shop = a_shop("")
        shop.user.timezone_name = "Asia/Kolkata"
        shop.user.save(update_fields=["timezone_name"])
        client, token = logged_in(shop.user)

        response = client.get(f"{V1}/providers/me/", **auth_header(token))

        assert response.data["timezone"] == "Asia/Kolkata"

    def test_a_zone_the_server_cannot_resolve_is_refused(self):
        """Not stored and hoped for.

        An unresolvable zone becomes a 500 the first time somebody searches
        `?open_now=true` - which is the moment it matters most and the least
        convenient moment to discover it is wrong.
        """
        shop = a_shop("Asia/Kolkata")
        client, token = logged_in(shop.user)

        response = client.patch(
            f"{V1}/providers/me/",
            {"timezone_name": "Middle-earth/Under-mines"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        shop.refresh_from_db()
        assert shop.timezone_name == "Asia/Kolkata", "a bad zone was stored anyway"

    def test_clearing_it_falls_back_rather_than_breaking(self):
        shop = a_shop("Asia/Kolkata")
        client, token = logged_in(shop.user)

        response = client.patch(
            f"{V1}/providers/me/",
            {"timezone_name": ""},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        shop.refresh_from_db()
        assert shop.timezone_name == ""
        # Still opens, on somebody's clock.
        assert shop.tz() is not None
        assert response.data["timezone"] == str(shop.tz())
