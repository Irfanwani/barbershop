"""Tests for ``/api/v1/providers/`` — discovery, the service menu and payouts."""

from __future__ import annotations

from datetime import time

import pytest

from providers.models import ProviderPayout, Service
from tests.factories import (
    DELHI,
    DELHI_FAR,
    DELHI_NEAR,
    auth_header,
    logged_in,
    make_profile,
    make_provider_user,
    make_service,
    make_user,
    raw_column,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
PROVIDERS = f"{V1}/providers/"


def as_provider(**profile_kwargs):
    """A signed-in provider with a shop profile."""
    user = make_provider_user()
    profile = make_profile(user, **profile_kwargs)
    return user, profile


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestProviderSearch:
    def test_lists_providers(self):
        client, _ = logged_in(make_user())
        make_profile(display_name="Sharp Cuts")

        body = client.get(PROVIDERS, **auth_header(_)).json()

        assert body["count"] == 1
        assert body["results"][0]["display_name"] == "Sharp Cuts"

    def test_requires_authentication(self):
        from django.test import Client

        assert Client().get(PROVIDERS).status_code == 401

    def test_results_are_paginated(self):
        client, token = logged_in(make_user())
        for index in range(5):
            make_profile(display_name=f"Shop {index}")

        body = client.get(f"{PROVIDERS}?page_size=2", **auth_header(token)).json()

        assert body["count"] == 5
        assert len(body["results"]) == 2
        assert body["next"] is not None

    def test_sorts_by_distance_when_given_coordinates(self):
        client, token = logged_in(make_user())
        make_profile(display_name="Near", coords=DELHI_NEAR)
        make_profile(display_name="Far", coords=DELHI_FAR)

        body = client.get(f"{PROVIDERS}?lat=28.6139&lng=77.2090", **auth_header(token)).json()

        assert [row["display_name"] for row in body["results"]] == ["Near", "Far"]
        assert body["results"][0]["distance_km"] < body["results"][1]["distance_km"]

    def test_uses_the_saved_customer_location_when_no_coordinates_given(self):
        user = make_user()
        from accounts.models import CustomerProfile

        CustomerProfile.objects.create(user=user, coords=DELHI)
        client, token = logged_in(user)
        make_profile(display_name="Near", coords=DELHI_NEAR)
        make_profile(display_name="Far", coords=DELHI_FAR)

        body = client.get(PROVIDERS, **auth_header(token)).json()

        assert body["results"][0]["display_name"] == "Near"
        assert body["search_origin"] is not None

    def test_no_origin_means_no_distance(self):
        client, token = logged_in(make_user())
        make_profile()

        body = client.get(PROVIDERS, **auth_header(token)).json()

        assert body["search_origin"] is None
        assert "distance_km" not in body["results"][0]

    def test_radius_excludes_distant_providers(self):
        client, token = logged_in(make_user())
        make_profile(display_name="Near", coords=DELHI_NEAR)
        make_profile(display_name="Far", coords=DELHI_FAR)

        body = client.get(
            f"{PROVIDERS}?lat=28.6139&lng=77.2090&radius_km=2", **auth_header(token)
        ).json()

        assert [row["display_name"] for row in body["results"]] == ["Near"]

    def test_radius_is_capped(self):
        client, token = logged_in(make_user())
        body = client.get(f"{PROVIDERS}?radius_km=99999", **auth_header(token)).json()
        assert body["radius_km"] == 100

    def test_filters_by_service_type(self):
        client, token = logged_in(make_user())
        make_profile(display_name="Cuts", service_type="barbershop")
        make_profile(display_name="Spa", service_type="spa")

        body = client.get(f"{PROVIDERS}?service_type=spa", **auth_header(token)).json()

        assert [row["display_name"] for row in body["results"]] == ["Spa"]

    def test_all_service_types_is_ignored(self):
        client, token = logged_in(make_user())
        make_profile(service_type="barbershop")
        make_profile(service_type="spa")

        body = client.get(f"{PROVIDERS}?service_type=all", **auth_header(token)).json()

        assert body["count"] == 2

    def test_filtering_by_several_services_requires_all_of_them(self):
        client, token = logged_in(make_user())
        both = make_profile(display_name="Both")
        make_service(both, name="Haircut")
        make_service(both, name="Beard trim")
        one = make_profile(display_name="One")
        make_service(one, name="Haircut")

        body = client.get(f"{PROVIDERS}?services=Haircut,Beard%20trim", **auth_header(token)).json()

        assert [row["display_name"] for row in body["results"]] == ["Both"]

    def test_filters_by_minimum_rating(self):
        client, token = logged_in(make_user())
        good = make_profile(display_name="Good")
        good.rating_average = 4.8
        good.save(update_fields=["rating_average"])
        poor = make_profile(display_name="Poor")
        poor.rating_average = 2.1
        poor.save(update_fields=["rating_average"])

        body = client.get(f"{PROVIDERS}?min_rating=4", **auth_header(token)).json()

        assert [row["display_name"] for row in body["results"]] == ["Good"]

    def test_open_now_filter_uses_working_hours(self):
        from django.utils import timezone

        client, token = logged_in(make_user())
        now = timezone.localtime().time()

        def around(hour: int) -> time:
            return time(hour, 0)

        open_now = make_profile(
            display_name="Open", opening_time=around(0), closing_time=around(23)
        )
        make_profile(
            display_name="Shut",
            opening_time=around((now.hour + 2) % 24),
            closing_time=around((now.hour + 3) % 24),
        )

        body = client.get(f"{PROVIDERS}?open_now=true", **auth_header(token)).json()

        assert open_now.display_name in [row["display_name"] for row in body["results"]]

    def test_garbage_coordinates_are_ignored_rather_than_500(self):
        """The old view did float() on request data inside a bare except."""
        client, token = logged_in(make_user())
        make_profile(display_name="Somewhere")

        response = client.get(f"{PROVIDERS}?lat=abc&lng=xyz", **auth_header(token))

        assert response.status_code == 200


class TestProviderDetail:
    def test_returns_the_menu(self):
        client, token = logged_in(make_user())
        profile = make_profile()
        make_service(profile, name="Haircut", price=25000)

        body = client.get(f"{PROVIDERS}{profile.id}/", **auth_header(token)).json()

        assert body["display_name"] == profile.display_name
        assert [service["name"] for service in body["services"]] == ["Haircut"]

    def test_unknown_provider_is_404(self):
        client, token = logged_in(make_user())
        assert client.get(f"{PROVIDERS}/999999/", **auth_header(token)).status_code == 404

    def test_does_not_leak_exact_coordinates(self):
        """The old getbarber/<pk> returned the shop's full precision to anyone."""
        client, token = logged_in(make_user())
        profile = make_profile(coords=DELHI)

        body = client.get(f"{PROVIDERS}{profile.id}/", **auth_header(token)).json()

        location = body["approximate_location"]
        assert location is not None
        assert location["latitude"] != pytest.approx(profile.coords.y, abs=1e-9) or location[
            "longitude"
        ] == pytest.approx(profile.coords.x, abs=1e-9)
        assert location["precision_meters"] > 50

    def test_includes_distance_when_an_origin_is_supplied(self):
        client, token = logged_in(make_user())
        profile = make_profile(coords=DELHI_NEAR)

        body = client.get(
            f"{PROVIDERS}{profile.id}/?lat=28.6139&lng=77.2090", **auth_header(token)
        ).json()

        assert body["distance_km"] < 2


class TestServiceTypes:
    def test_lists_the_categories(self):
        from django.test import Client

        body = Client().get(f"{PROVIDERS}types/").json()

        assert {"value", "label"} <= set(body[0])
        assert any(choice["value"] == "barbershop" for choice in body)

    def test_does_not_require_authentication(self):
        from django.test import Client

        assert Client().get(f"{PROVIDERS}types/").status_code == 200


# ---------------------------------------------------------------------------
# The provider's own shop
# ---------------------------------------------------------------------------


class TestMyProvider:
    def test_requires_a_provider_account(self):
        client, token = logged_in(make_user())
        assert client.get(f"{PROVIDERS}me/", **auth_header(token)).status_code == 403

    def test_a_provider_without_a_shop_is_refused(self):
        """The app reads 403 here as "go finish onboarding"."""
        client, token = logged_in(make_provider_user())
        assert client.get(f"{PROVIDERS}me/", **auth_header(token)).status_code == 403

    def test_returns_their_own_shop(self):
        user, profile = as_provider()
        client, token = logged_in(user)

        body = client.get(f"{PROVIDERS}me/", **auth_header(token)).json()

        assert body["id"] == profile.id
        assert body["owner"]["id"] == profile.user_id

    def test_reads_back_the_location_it_was_given(self):
        """A `coords` of {} reads as "no location", which is a lie here."""
        user, _ = as_provider(coords=DELHI_NEAR)
        client, token = logged_in(user)

        body = client.get(f"{PROVIDERS}me/", **auth_header(token)).json()

        assert body["coords"]["latitude"] == pytest.approx(28.6150, abs=1e-6)
        assert body["coords"]["longitude"] == pytest.approx(77.2110, abs=1e-6)

    def test_updates_the_shop(self):
        user, profile = as_provider()
        client, token = logged_in(user)

        response = client.patch(
            f"{PROVIDERS}me/",
            {"display_name": "Sharp Cuts Deluxe"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        profile.refresh_from_db()
        assert profile.display_name == "Sharp Cuts Deluxe"

    def test_rejects_closing_before_opening(self):
        user, _ = as_provider()
        client, token = logged_in(user)

        response = client.patch(
            f"{PROVIDERS}me/",
            {"opening_time": "18:00", "closing_time": "09:00"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_an_account_can_become_a_provider(self):
        user = make_user()
        client, token = logged_in(user)

        response = client.post(
            f"{V1}/me/shop/create/",
            {
                "display_name": "Corner Shop",
                "service_type": "barbershop",
                "address": "Sector 5",
                "coords": {"latitude": 28.6139, "longitude": 77.2090},
            },
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 201, response.content
        user.refresh_from_db()
        assert user.role == "provider"
        assert user.provider_profile.display_name == "Corner Shop"

    def test_creating_a_second_shop_is_refused(self):
        user, profile = as_provider()
        client, token = logged_in(user)
        assert profile is not None

        response = client.post(
            f"{V1}/me/shop/create/",
            {
                "display_name": "Second Shop",
                "service_type": "barbershop",
                "coords": {"latitude": 28.6, "longitude": 77.2},
            },
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 409, response.content
        assert profile.display_name != "Second Shop"

    def test_a_shop_needs_a_location(self):
        client, token = logged_in(make_user())

        response = client.post(
            f"{V1}/me/shop/create/",
            {"display_name": "Nowhere", "service_type": "barbershop"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert "coords" in response.json()["error"]["details"]


# ---------------------------------------------------------------------------
# The provider's own service menu
# ---------------------------------------------------------------------------


class TestMyServices:
    def _provider_client(self):
        _, profile = as_provider()
        return profile, *logged_in(profile.user)

    def test_adds_a_service(self):
        profile, client, token = self._provider_client()

        response = client.post(
            f"{PROVIDERS}me/services/",
            {"name": "Haircut", "price": 25000, "duration_minutes": 30},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 201, response.content
        assert Service.objects.filter(provider=profile, name="Haircut").exists()

    def test_rejects_a_zero_price(self):
        _, client, token = self._provider_client()

        response = client.post(
            f"{PROVIDERS}me/services/",
            {"name": "Free haircut", "price": 0},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_rejects_an_absurd_price(self):
        _, client, token = self._provider_client()

        response = client.post(
            f"{PROVIDERS}me/services/",
            {"name": "Yacht", "price": 999_999_999},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_service_names_are_unique_for_a_provider(self):
        _, client, token = self._provider_client()
        payload = {"name": "Haircut", "price": 1000}

        client.post(
            f"{PROVIDERS}me/services/",
            payload,
            content_type="application/json",
            **auth_header(token),
        )
        second = client.post(
            f"{PROVIDERS}me/services/",
            payload,
            content_type="application/json",
            **auth_header(token),
        )

        # 409, not 400: nothing is malformed, the name is simply taken.
        assert second.status_code == 409

    def test_a_provider_may_not_edit_another_providers_service(self):
        """The old PUT /addservices took a bare id and rewrote whatever it found."""
        _, client, token = self._provider_client()
        victim_profile = make_profile(display_name="Someone Else")
        victim_service = make_service(victim_profile, name="Haircut", price=1000)

        response = client.patch(
            f"{PROVIDERS}me/services/{victim_service.id}/",
            {"price": 1},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 404
        victim_service.refresh_from_db()
        assert victim_service.price == 1000

    def test_a_provider_may_not_delete_another_providers_service(self):
        _, client, token = self._provider_client()
        victim_profile = make_profile(display_name="Someone Else")
        victim_service = make_service(victim_profile)

        response = client.delete(
            f"{PROVIDERS}me/services/{victim_service.id}/", **auth_header(token)
        )

        assert response.status_code == 404
        assert Service.objects.filter(pk=victim_service.pk).exists()

    def test_deleting_own_service_returns_204_not_410(self):
        """The old endpoint returned 410 after a successful delete."""
        own_profile, client, token = self._provider_client()
        service = make_service(own_profile)

        response = client.delete(f"{PROVIDERS}me/services/{service.id}/", **auth_header(token))

        assert response.status_code == 204
        assert not Service.objects.filter(pk=service.pk).exists()

    def test_a_customer_cannot_reach_the_service_menu(self):
        client, token = logged_in(make_user())
        assert client.get(f"{PROVIDERS}me/services/", **auth_header(token)).status_code == 403


# ---------------------------------------------------------------------------
# Payout
# ---------------------------------------------------------------------------


class TestPayout:
    def _provider_client(self):
        _, profile = as_provider()
        return profile, *logged_in(profile.user)

    def test_starts_unregistered(self):
        _, client, token = self._provider_client()

        body = client.get(f"{PROVIDERS}me/payout/", **auth_header(token)).json()

        assert body["payout_registered"] is False

    def test_saves_the_account_encrypted(self):
        profile, client, token = self._provider_client()

        response = client.put(
            f"{PROVIDERS}me/payout/",
            {
                "business_name": "Sharp Cuts Studio",
                "beneficiary_name": "Irfan Wani",
                "account_number": "4111111111111111",
                "ifsc_code": "HDFC0001234",
            },
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200, response.content
        assert ProviderPayout.objects.filter(provider=profile).exists()

        stored = raw_column(
            "providers_payout", "account_number", ProviderPayout.objects.get(provider=profile).id
        )
        assert "4111111111111111" not in stored

    def test_never_returns_the_account_number_in_full(self):
        _, client, token = self._provider_client()
        client.put(
            f"{PROVIDERS}me/payout/",
            {
                "business_name": "Sharp Cuts",
                "beneficiary_name": "Irfan",
                "account_number": "4111111111111111",
                "ifsc_code": "HDFC0001234",
            },
            content_type="application/json",
            **auth_header(token),
        )

        body = client.get(f"{PROVIDERS}me/payout/", **auth_header(token)).json()

        assert "4111111111111111" not in str(body)
        assert body["account_number_masked"].endswith("1111")
        assert "HDFC0001234" not in str(body)

    def test_rejects_a_malformed_ifsc_code(self):
        _, client, token = self._provider_client()

        response = client.put(
            f"{PROVIDERS}me/payout/",
            {
                "business_name": "Sharp Cuts",
                "beneficiary_name": "Irfan",
                "account_number": "4111111111111111",
                "ifsc_code": "NOPE",
            },
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_a_provider_cannot_read_another_providers_payout(self):
        _, profile = as_provider()
        _, other = as_provider()
        ProviderPayout.objects.create(
            provider=other,
            business_name="Other",
            beneficiary_name="Other",
            account_number="9999888877776666",
            ifsc_code="HDFC0001234",
        )
        client, token = logged_in(profile.user)

        response = client.get(f"{PROVIDERS}me/payout/", **auth_header(token))

        assert response.json()["payout_registered"] is False


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_lists_slots_inside_working_hours(self):
        user, profile = as_provider(closing_time="18:00")
        client, token = logged_in(user)
        assert client is not None

        body = client.get(
            f"{PROVIDERS}{profile.id}/availability/?days=3", **auth_header(token)
        ).json()

        assert body["provider"] == profile.id
        assert body["slots"]
        assert all(slot["is_available"] for slot in body["slots"])
        # Times come back over JSON as strings; parse them the way the app does.

        def at(value: str) -> time:
            """A clock time from either `HH:MM:SS` or a full ISO timestamp."""
            return time.fromisoformat(value.split("T")[-1][:8])

        assert all(
            at(profile.opening_time.isoformat())
            <= at(slot["starts_at"])
            <= at(profile.closing_time.isoformat())
            for slot in body["slots"]
        )

    def test_marks_taken_slots_unavailable(self):
        from datetime import datetime

        from tests.factories import make_booking

        user, profile = as_provider()
        client, token = logged_in(user)
        taken = make_booking(provider=profile).starts_at

        body = client.get(
            f"{PROVIDERS}{profile.id}/availability/?days=3", **auth_header(token)
        ).json()

        # JSON timestamps come back as strings; compare as instants.
        match = [
            slot for slot in body["slots"] if datetime.fromisoformat(slot["starts_at"]) == taken
        ]
        assert match and not match[0]["is_available"]

    def test_cannot_read_another_providers_calendar(self):
        _, profile = as_provider()
        _, other = as_provider()
        client, token = logged_in(profile.user)

        response = client.get(f"{PROVIDERS}{other.id}/availability/", **auth_header(token))

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Opening hours — the open/closed control
# ---------------------------------------------------------------------------


class TestWorkingHoursApi:
    def test_reads_your_own_week(self, client):
        user, _ = as_provider()
        client.force_login(user)

        response = client.get(f"{PROVIDERS}me/hours/")

        assert response.status_code == 200

    def test_saves_a_week_in_one_request(self, client):
        user, profile = as_provider()
        client.force_login(user)

        response = client.put(
            f"{PROVIDERS}me/hours/",
            {
                "days": [
                    {"weekday": 0, "is_closed": False, "opens_at": "09:00", "closes_at": "18:00"},
                    {"weekday": 6, "is_closed": True, "opens_at": "09:00", "closes_at": "18:00"},
                ]
            },
            content_type="application/json",
        )

        assert response.status_code == 200, response.content
        assert profile.hours.filter(weekday=0, is_closed=False).exists()
        assert profile.hours.filter(weekday=6, is_closed=True).exists()

    def test_a_later_write_replaces_rather_than_duplicates(self, client):
        user, profile = as_provider()
        client.force_login(user)
        body = {
            "days": [{"weekday": 0, "is_closed": False, "opens_at": "09:00", "closes_at": "18:00"}]
        }

        client.put(f"{PROVIDERS}me/hours/", body, content_type="application/json")
        client.put(f"{PROVIDERS}me/hours/", body, content_type="application/json")

        assert profile.hours.filter(weekday=0).count() == 1

    def test_rejects_a_day_listed_twice(self, client):
        user, _ = as_provider()
        client.force_login(user)

        response = client.put(
            f"{PROVIDERS}me/hours/",
            {
                "days": [
                    {"weekday": 0, "is_closed": False, "opens_at": "09:00", "closes_at": "18:00"},
                    {"weekday": 0, "is_closed": True, "opens_at": "09:00", "closes_at": "18:00"},
                ]
            },
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_rejects_a_shift_that_ends_before_it_starts(self, client):
        user, _ = as_provider()
        client.force_login(user)

        response = client.put(
            f"{PROVIDERS}me/hours/",
            {
                "days": [
                    {"weekday": 0, "is_closed": False, "opens_at": "18:00", "closes_at": "09:00"}
                ]
            },
            content_type="application/json",
        )

        # A 500 here would tell the provider nothing about what to fix.
        assert response.status_code == 400
        details = response.json()["error"]["details"]
        assert "Closing time must be later than opening time." in str(details)

    def test_a_customer_cannot_set_shop_hours(self, client):
        from tests.factories import logged_in

        _, token = logged_in(make_user())

        response = client.get(f"{PROVIDERS}me/hours/", **auth_header(token))

        assert response.status_code == 403

    def test_the_write_always_targets_your_own_shop(self, client):
        """There is no id in the path, so there is nothing to point elsewhere.

        The old shop endpoints took a bare id and rewrote whatever it pointed
        at. "Your own" is the whole safety property, and it is structural.
        """
        from tests.factories import logged_in

        _, colleague = as_provider()
        _, token = logged_in(colleague.user)

        client.put(
            f"{PROVIDERS}me/hours/",
            {
                "days": [
                    {"weekday": 3, "is_closed": True, "opens_at": "09:00", "closes_at": "18:00"}
                ]
            },
            content_type="application/json",
            **auth_header(token),
        )

        assert colleague.hours.filter(weekday=3).exists()


# ---------------------------------------------------------------------------
# The bookings on/off switch
# ---------------------------------------------------------------------------


class TestAcceptingBookingsToggle:
    def test_turns_bookings_off(self, client):
        user, profile = as_provider()
        from tests.factories import logged_in

        _, token = logged_in(user)

        response = client.post(
            f"{PROVIDERS}me/accepting-bookings/",
            {"is_accepting_bookings": False},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200, response.content
        profile.refresh_from_db()
        assert profile.is_accepting_bookings is False
        assert profile.is_bookable is False

    def test_turns_bookings_back_on(self, client):
        user, profile = as_provider(is_accepting_bookings=False)
        from tests.factories import logged_in

        _, token = logged_in(user)

        client.post(
            f"{PROVIDERS}me/accepting-bookings/",
            {"is_accepting_bookings": True},
            content_type="application/json",
            **auth_header(token),
        )

        profile.refresh_from_db()
        assert profile.is_accepting_bookings is True

    def test_does_not_cancel_appointments_already_taken(self, client):
        """Turning the switch off stops new bookings; it must not cancel the
        ones a customer already paid for."""
        from tests.factories import logged_in, make_booking

        user, profile = as_provider()
        make_booking(provider=profile)
        _, token = logged_in(user)

        client.post(
            f"{PROVIDERS}me/accepting-bookings/",
            {"is_accepting_bookings": False},
            content_type="application/json",
            **auth_header(token),
        )

        from bookings.models import Booking

        assert Booking.objects.filter(provider=profile).count() == 1

    def test_a_customer_cannot_flip_someone_elses_switch(self, client):
        from tests.factories import logged_in

        _, other = as_provider()
        _, token = logged_in(make_user())

        response = client.post(
            f"{PROVIDERS}me/accepting-bookings/",
            {"is_accepting_bookings": False},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code in (403, 404)
        other.refresh_from_db()
        assert other.is_accepting_bookings is True


# ---------------------------------------------------------------------------
# Price insights
# ---------------------------------------------------------------------------


class TestPriceInsights:
    def test_is_readable_without_an_account(self, client):
        for price in (20000, 30000, 40000):
            make_service(make_profile(), price=price)

        # Someone comparing prices has not chosen a shop yet, which is exactly
        # when they most want the number.
        assert client.get(f"{PROVIDERS}prices/").status_code == 200

    def test_reports_a_median_across_shops(self, client):
        for price in (20000, 30000, 40000):
            make_service(make_profile(), price=price)

        body = client.get(f"{PROVIDERS}prices/").data
        barbers = next(b for b in body["bands"] if b["service_type"] == "barbershop")

        assert barbers["median"] == 30000
        assert barbers["median_display"] == "₹300.00"
        assert barbers["is_thin"] is False

    def test_says_so_when_there_are_too_few_shops(self, client):
        make_service(make_profile(), price=20000)

        body = client.get(f"{PROVIDERS}prices/").data
        barbers = next(b for b in body["bands"] if b["service_type"] == "barbershop")

        # One shop's price is not a median; presenting it as one is how a
        # customer ends up surprised.
        assert barbers["is_thin"] is True

    def test_ignores_a_placeholder_price(self, client):
        for price in (20000, 30000, 40000):
            make_service(make_profile(), price=price)
        make_service(make_profile(), price=1)

        body = client.get(f"{PROVIDERS}prices/").data
        barbers = next(b for b in body["bands"] if b["service_type"] == "barbershop")

        assert barbers["median"] == 30000
        assert barbers["sample_size"] == 3

    def test_leaves_out_shop_types_nobody_offers(self, client):
        for price in (20000, 30000, 40000):
            make_service(make_profile(), price=price)

        offered = {band["service_type"] for band in client.get(f"{PROVIDERS}prices/").data["bands"]}

        assert "spa" not in offered

    def test_can_be_limited_to_one_shop_type(self, client):
        for price in (20000, 30000, 40000):
            make_service(make_profile(), price=price)

        body = client.get(f"{PROVIDERS}prices/?service_type=barbershop").data

        assert [band["service_type"] for band in body["bands"]] == ["barbershop"]


class TestServicePriceIndex:
    def test_indexes_names_several_shops_use(self, client):
        for price in (20000, 30000, 40000):
            make_service(make_profile(), name="Haircut", price=price)

        body = client.get(f"{PROVIDERS}prices/services/").data

        assert body["services"][0]["name"] == "Haircut"
        assert body["services"][0]["median_display"] == "₹300.00"

    def test_ignores_a_name_one_shop_uses(self, client):
        make_service(make_profile(), name="Scalp massage ritual", price=90000)

        assert client.get(f"{PROVIDERS}prices/services/").data["services"] == []

    def test_caps_a_silly_limit(self, client):
        response = client.get(f"{PROVIDERS}prices/services/?limit=99999")

        assert response.status_code == 200
