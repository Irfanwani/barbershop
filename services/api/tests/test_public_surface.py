"""What someone can see before they have an account.

The marketing site reads the API with no token, so every endpoint it calls must
work anonymously. It did not: `GET /providers/` was authenticated, so the shop
list silently rendered as "Shops are not loading" in production while the rest
of the page looked fine.

These tests are the regression. Each one fails if the endpoint it names goes
back behind a login.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIRequestFactory

from tests.factories import (
    DELHI,
    make_profile,
    make_service,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"


class TestAnonymousBrowsing:
    """Endpoints the marketing site calls without a token."""

    def test_shop_search_works_without_an_account(self, client):
        make_profile(display_name="Sharp Cuts Studio")

        # Someone deciding whether to download the app has not signed up yet.
        response = client.get(f"{V1}/providers/")

        assert response.status_code == 200
        assert response.data["count"] == 1

    def test_shop_search_still_sorts_by_distance_anonymously(self, client):
        near = make_profile(display_name="Near", coords=DELHI)
        make_service(near)

        response = client.get(f"{V1}/providers/?lat=28.6139&lng=77.2090")

        assert response.status_code == 200
        assert response.data["search_origin"] == {
            "latitude": 28.6139,
            "longitude": 77.2090,
        }

    def test_price_bands_work_without_an_account(self, client):
        for price in (20000, 30000, 40000):
            make_service(make_profile(), price=price)

        assert client.get(f"{V1}/providers/prices/").status_code == 200

    def test_the_service_price_index_works_without_an_account(self, client):
        for price in (20000, 30000, 40000):
            make_service(make_profile(), name="Haircut", price=price)

        assert client.get(f"{V1}/providers/prices/services/").status_code == 200

    def test_shop_categories_work_without_an_account(self, client):
        assert client.get(f"{V1}/providers/types/").status_code == 200

    def test_product_browsing_works_without_an_account(self, client):
        from tests.factories import make_product

        make_product()

        assert client.get(f"{V1}/products/").status_code == 200

    def test_a_review_summary_works_without_an_account(self, client):
        assert client.get(f"{V1}/reviews/shops/1/summary/").status_code in (200, 404)

    def test_an_anonymous_searcher_gets_no_saved_location(self, client):
        """There is no profile to read, so results must not be ranked by one."""
        from tests.factories import DELHI_FAR

        make_profile(display_name="Somewhere else", coords=DELHI_FAR)

        response = client.get(f"{V1}/providers/")

        assert response.status_code == 200
        assert response.data["search_origin"] is None


class TestStillPrivate:
    """Public browsing must not become public everything."""

    def test_a_shop_menu_is_not_public(self, client):
        provider = make_profile()
        make_service(provider)

        # Availability is per-customer reasoning about someone's calendar.
        # The list may be public; the detail that follows a sign-in may not.
        assert client.get(f"{V1}/providers/{provider.id}/").status_code == 401

    def test_availability_is_not_public(self, client):
        provider = make_profile()

        assert client.get(f"{V1}/providers/{provider.id}/availability/").status_code == 401

    def test_someone_elses_bookings_are_not_public(self, client):
        make_profile()

        assert client.get(f"{V1}/bookings/").status_code == 401

    def test_an_order_reference_is_not_public(self, client):
        assert client.get(f"{V1}/products/orders/OR-ABC123/").status_code == 401

    def test_the_price_search_does_not_leak_exact_coordinates(self, client):
        """Rounded to ~111 m, which is enough for a map marker and no more."""
        provider = make_profile(coords=DELHI)

        response = client.get(f"{V1}/providers/")
        location = response.data["results"][0]["approximate_location"]

        assert location["precision_meters"] == 111
        # Not the shop's own coordinate.
        assert location["latitude"] != provider.coords.y


class TestAnonymousThrottling:
    def test_shop_search_is_rate_limited(self, monkeypatch):
        """An anonymous caller can page through every shop on the platform.

        This is the endpoint an unauthenticated scraper would use, so it is
        throttled harder than anything a signed-in user can do.
        """
        from django.core.cache import cache
        from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle
        from rest_framework.views import APIView

        from providers.views import ProviderListView

        make_profile()

        # The test settings disable throttling entirely so suites are not
        # flaky. DRF resolves both the classes and the rates at *import* time,
        # onto class attributes, so `override_settings` cannot reach them and
        # this would otherwise pass against no throttle at all.
        monkeypatch.setattr(APIView, "throttle_classes", [ScopedRateThrottle])
        monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", {"public_search": "5/min"})
        cache.clear()

        factory = APIRequestFactory()
        view = ProviderListView.as_view()

        codes = [view(factory.get("/api/v1/providers/")).status_code for _ in range(10)]
        cache.clear()

        assert 200 in codes, "throttling blocked every request"
        assert 429 in codes, "public search is not being throttled"
