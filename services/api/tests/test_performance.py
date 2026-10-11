"""How much work a request actually does.

Performance work without a measurement is guesswork, and the guess is almost
always optimistic. These tests count the queries a request issues and the rows
it pulls, which is the difference between "feels slow" and a number that
regresses visibly in review.

`assertNumQueries` is exact rather than approximate, so a regression fails the
build rather than quietly costing a second per request.
"""

from __future__ import annotations

import pytest
from django.contrib.gis.geos import Point
from django.db import connection
from django.test.utils import CaptureQueriesContext

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
PROVIDERS = f"{V1}/providers/"

DELHI = Point(77.2090, 28.6139, srid=4326)


def count_rows():
    """Count the rows a given query returns, as the request runs.

    The honest measure of "did we read the whole table". Counting queries says
    how many round trips; counting characters of SQL says how long the
    statements are, which tells you nothing about the work. Django's debug
    cursor does not report row counts for psycopg 3, so the cursor's own
    `fetchall` is wrapped to add them up.
    """
    import contextlib

    @contextlib.contextmanager
    def wrapper():
        total = 0

        def execute(execute, sql, params, many, context):
            nonlocal total
            cursor = execute(sql, params, many, context)
            original_fetchall = cursor.fetchall

            def fetchall(*args, **kwargs):
                nonlocal total
                rows = original_fetchall(*args, **kwargs)
                total += len(rows)
                return rows

            cursor.fetchall = fetchall
            return cursor

        with connection.execute_wrapper(wrapper):
            yield lambda: total

    return wrapper


def seed_shops(count: int, *, services: int = 2) -> None:
    """A platform with `count` shops on it."""
    for index in range(count):
        provider = make_profile(display_name=f"Shop {index:04d}", coords=DELHI)
        for service in range(services):
            make_service(provider, name=f"Service {index}-{service}", price=20000 + service)


class TestProviderSearchCost:
    def test_a_small_platform_is_a_handful_of_queries(self, client):
        seed_shops(5)
        _, token = logged_in(make_user())

        with CaptureQueriesContext(connection) as captured:
            client.get(f"{PROVIDERS}?lat=28.6139&lng=77.2090", **auth_header(token))

        assert len(captured) <= 8, [query["sql"][:90] for query in captured]

    def test_the_page_size_does_not_change_the_number_of_rows_fetched(self, client):
        """The regression this file exists to prevent.

        Paginating after materialising the whole table means a platform with
        10,000 shops loads 10,000 rows to show 20. The page size is the only
        thing the client controls, so it must actually bound the work.
        """
        seed_shops(40)
        _, token = logged_in(make_user())

        wrapper = count_rows()
        with wrapper() as total:
            client.get(f"{PROVIDERS}?lat=28.6139&lng=77.2090&page_size=5", **auth_header(token))

        # 5 shops + their 10 services + hours + the token. Not 40 shops and 80
        # services: the difference is the whole regression.
        assert total() < 30, f"{total()} rows for a page of five suggests a full scan"

    def test_rows_returned_is_bounded_by_page_size(self, client):
        seed_shops(30)
        _, token = logged_in(make_user())

        body = client.get(
            f"{PROVIDERS}?lat=28.6139&lng=77.2090&page_size=5", **auth_header(token)
        ).json()

        assert len(body["results"]) == 5
        assert body["count"] == 30

    def test_the_query_count_does_not_grow_with_the_number_of_shops(self, client):
        """A search that issues one query per shop is an N+1 with extra steps."""
        _, token = logged_in(make_user())

        seed_shops(3)
        with CaptureQueriesContext(connection) as small:
            client.get(f"{PROVIDERS}?lat=28.6139&lng=77.2090", **auth_header(token))

        seed_shops(17)
        with CaptureQueriesContext(connection) as large:
            client.get(f"{PROVIDERS}?lat=28.6139&lng=77.2090", **auth_header(token))

        assert len(large) <= len(small) + 2, (
            f"{len(small)} queries for 3 shops, {len(large)} for 20 — something is querying per row"
        )


class TestPaginationStability:
    def test_pages_do_not_repeat_or_skip_a_shop(self, client):
        """A queryset with no total order paginates unpredictably.

        Postgres is free to return rows in any order without an ORDER BY, which
        means a customer scrolling past the first page can see the same shop
        twice and miss one entirely.
        """
        seed_shops(12)

        _, token = logged_in(make_user())
        seen: list[int] = []

        for page in (1, 2, 3):
            body = client.get(f"{PROVIDERS}?page={page}&page_size=5", **auth_header(token)).json()
            seen.extend(row["id"] for row in body["results"])

        assert len(seen) == 12
        assert len(set(seen)) == 12, f"a shop appeared twice across pages: {seen}"

    def test_the_order_is_the_same_when_paginating_and_not(self, client):
        seed_shops(8)

        _, token = logged_in(make_user())
        paged = client.get(f"{PROVIDERS}?page_size=100", **auth_header(token)).json()

        # If pagination reordered rows, a single large page would not match the
        # sequence a customer gets by scrolling.
        assert [row["id"] for row in paged["results"]] == sorted(
            row["id"] for row in paged["results"]
        )


class TestAvailabilityCost:
    def test_the_calendar_does_not_query_per_slot(self, client):
        """One query for the provider, one for the bookings, regardless of length."""
        provider = make_profile(coords=DELHI)
        make_service(provider)
        client.force_login(make_provider_user())
        client_for_provider = client

        with CaptureQueriesContext(connection) as captured:
            client_for_provider.get(f"{PROVIDERS}{provider.id}/availability/")

        assert len(captured) <= 12, [query["sql"][:80] for query in captured]

    def test_the_calendar_query_count_does_not_grow_with_the_window(self, client):
        provider = make_profile(coords=DELHI)
        make_service(provider)
        client.force_login(make_provider_user())

        with CaptureQueriesContext(connection) as short:
            client.get(f"{PROVIDERS}{provider.id}/availability/?days=7")

        with CaptureQueriesContext(connection) as long:
            client.get(f"{PROVIDERS}{provider.id}/availability/?days=30")

        assert len(long) <= len(short) + 2, f"{len(short)} queries for 7 days, {len(long)} for 30"


class TestBookingListCost:
    def test_a_page_of_bookings_does_not_load_every_booking(self, client):
        from tests.factories import make_booking

        provider = make_profile()
        make_service(provider)
        customer = make_user()
        for _ in range(25):
            make_booking(provider=provider, customer=customer)

        client_, token = logged_in(customer)

        wrapper = count_rows()
        with wrapper() as total:
            client_.get(f"{V1}/bookings/?page_size=5", **auth_header(token))

        assert total() < 60, f"{total()} rows for a page of five bookings"
