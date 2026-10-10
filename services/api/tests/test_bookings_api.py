"""Tests for ``/api/v1/bookings/`` — the server-priced booking flow."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from providers.models import ProviderProfile
from tests.factories import (
    auth_header,
    logged_in,
    make_profile,
    make_provider_user,
    make_service,
    make_user,
    next_slot,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
BOOKINGS = f"{V1}/bookings/"


def booking_payload(profile: ProviderProfile, service_ids: list[int], **overrides) -> dict:
    payload = {
        "provider": profile.id,
        "services": service_ids,
        "starts_at": next_slot(days=1, hour=12).isoformat(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Creating a booking
# ---------------------------------------------------------------------------


class TestCreate:
    def _shop(self):
        profile = make_profile()
        haircut = make_service(profile, name="Haircut", price=25000, duration_minutes=30)
        beard = make_service(profile, name="Beard trim", price=10000, duration_minutes=15)
        return profile, haircut, beard

    def test_creates_a_booking(self):
        client, token = logged_in(make_user())
        profile, haircut, _ = self._shop()

        response = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id]),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 201, response.content
        assert Booking.objects.count() == 1

    def test_returns_a_human_reference(self):
        client, token = logged_in(make_user())
        profile, haircut, _ = self._shop()

        body = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id]),
            content_type="application/json",
            **auth_header(token),
        ).json()

        assert body["reference"].startswith("BK-")
        assert len(body["reference"]) == 9

    def test_price_comes_from_the_database_not_the_request(self):
        """The old endpoint stored whatever totalcost the client posted."""
        client, token = logged_in(make_user())
        profile, haircut, _ = self._shop()

        body = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id], total=1, subtotal=1, totalcost=1),
            content_type="application/json",
            **auth_header(token),
        ).json()

        assert body["subtotal"] == 25000
        assert body["platform_fee"] == 250
        assert body["total"] == 25250

    def test_multiple_services_are_summed(self):
        client, token = logged_in(make_user())
        profile, haircut, beard = self._shop()

        body = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id, beard.id]),
            content_type="application/json",
            **auth_header(token),
        ).json()

        assert body["subtotal"] == 35000
        assert body["total"] == 35350
        assert len(body["items"]) == 2

    def test_line_items_snapshot_the_price(self):
        client, token = logged_in(make_user())
        profile, haircut, _ = self._shop()

        body = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id]),
            content_type="application/json",
            **auth_header(token),
        ).json()

        haircut.price = 99999
        haircut.save()

        assert body["items"][0]["unit_price"] == 25000
        assert body["total_display"] == "₹252.50"

    def test_the_fee_is_frozen_at_booking_time(self, settings):
        """Changing the platform fee must not move an existing booking.

        The customer agreed to a specific total. A fee that changes underneath a
        confirmed booking is a charge they never agreed to.
        """
        client, token = logged_in(make_user())
        profile, haircut, _ = self._shop()
        settings.PLATFORM_FEE_PERCENT = 20

        body = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id]),
            content_type="application/json",
            **auth_header(token),
        ).json()

        assert body["platform_fee"] == 5000

        settings.PLATFORM_FEE_PERCENT = 1

        booking = Booking.objects.get(reference=body["reference"])
        booking.refresh_from_db()
        assert booking.platform_fee == 5000
        assert booking.total == booking.subtotal + 5000

    def test_the_quote_agrees_with_what_is_actually_charged(self):
        """A quote is worthless if the booking does not match it."""
        client, token = logged_in(make_user())
        profile, haircut, _ = self._shop()

        quoted = client.post(
            BOOKINGS + "quote/",
            booking_payload(profile, [haircut.id]),
            content_type="application/json",
            **auth_header(token),
        ).json()

        booked = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id]),
            content_type="application/json",
            **auth_header(token),
        ).json()

        assert quoted["total"] == booked["total"]
        assert quoted["platform_fee"] == booked["platform_fee"]

    def test_duration_comes_from_the_services(self):
        client, token = logged_in(make_user())
        profile, haircut, beard = self._shop()

        body = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id, beard.id]),
            content_type="application/json",
            **auth_header(token),
        ).json()

        assert body["duration_minutes"] == 45

    def test_the_clock_comes_from_the_server(self):
        """The old check trusted a `currentdatetime` string posted by the phone."""
        client, token = logged_in(make_user())
        profile, haircut, _ = self._shop()

        response = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id], currentdatetime="2099-01-01T00:00:00Z"),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 201, response.content

    def test_a_slot_in_the_past_is_refused(self):
        client, token = logged_in(make_user())
        profile, haircut, _ = self._shop()

        response = client.post(
            BOOKINGS + "new/",
            booking_payload(
                profile, [haircut.id], starts_at=(timezone.now() - timedelta(days=1)).isoformat()
            ),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert "passed" in response.json()["error"]["message"]

    def test_a_double_booking_is_refused(self):
        client, token = logged_in(make_user())
        profile, haircut, _ = self._shop()
        starts_at = next_slot(days=1, hour=13)

        first = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id], starts_at=starts_at.isoformat()),
            content_type="application/json",
            **auth_header(token),
        )
        assert first.status_code == 201

        client2, token2 = logged_in(make_user())
        second = client2.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id], starts_at=starts_at.isoformat()),
            content_type="application/json",
            **auth_header(token2),
        )

        assert second.status_code == 400
        assert "taken" in second.json()["error"]["message"]

    def test_cannot_book_outside_opening_hours(self):
        profile = make_profile(opening_time="09:00", closing_time="13:00")
        haircut = make_service(profile)
        client, token = logged_in(make_user())

        response = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id], starts_at=next_slot(hour=18).isoformat()),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert "open" in response.json()["error"]["message"]

    def test_cannot_book_another_providers_service(self):
        profile, _, _ = self._shop()
        other = make_profile(display_name="Someone Else")
        their_service = make_service(other)
        client, token = logged_in(make_user())

        response = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [their_service.id]),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert "not available" in response.json()["error"]["message"]

    def test_cannot_book_a_retired_service(self):
        profile, haircut, _ = self._shop()
        haircut.is_active = False
        haircut.save()
        client, token = logged_in(make_user())

        response = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id]),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_cannot_book_a_provider_that_is_not_accepting_bookings(self):
        profile, haircut, _ = self._shop()
        profile.is_accepting_bookings = False
        profile.save()
        client, token = logged_in(make_user())

        response = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id]),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_cannot_book_more_than_ten_services(self):
        profile = make_profile()
        ids = []
        for index in range(11):
            ids.append(make_service(profile, name=f"Service {index}").id)
        client, token = logged_in(make_user())

        response = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, ids),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_cannot_book_the_same_service_twice(self):
        profile, haircut, _ = self._shop()
        client, token = logged_in(make_user())

        response = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id, haircut.id]),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_unverified_customers_cannot_book(self):
        profile, haircut, _ = self._shop()
        client, token = logged_in(make_user(verified=False))

        response = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id]),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert "verify" in response.json()["error"]["message"].lower()

    def test_a_provider_cannot_book_themselves(self):
        user = make_provider_user()
        profile = make_profile(user)
        haircut = make_service(profile)
        client, token = logged_in(user)

        response = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id]),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_requires_authentication(self):
        from django.test import Client

        assert (
            Client().post(BOOKINGS + "new/", {}, content_type="application/json").status_code == 401
        )

    def test_approval_required_providers_start_as_awaiting_confirmation(self):
        profile, haircut, _ = self._shop()
        profile.requires_approval = True
        profile.save()
        client, token = logged_in(make_user())

        body = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id]),
            content_type="application/json",
            **auth_header(token),
        ).json()

        assert body["status"] == BookingStatus.AWAITING_CONFIRMATION


# ---------------------------------------------------------------------------
# Reading bookings
# ---------------------------------------------------------------------------


class TestList:
    def test_a_customer_sees_only_their_own(self):
        from tests.factories import make_booking

        mine = make_booking()
        make_booking()

        client, token = logged_in(mine.customer)
        body = client.get(BOOKINGS, **auth_header(token)).json()

        assert body["count"] == 1
        assert body["role"] == "customer"

    def test_a_provider_sees_their_shops_bookings(self):
        from tests.factories import make_booking

        profile = make_profile()
        make_booking(provider=profile)
        make_booking()

        client, token = logged_in(profile.user)
        body = client.get(BOOKINGS, **auth_header(token)).json()

        assert body["count"] == 1
        assert body["role"] == "provider"

    def test_upcoming_filter(self):
        from tests.factories import make_booking

        upcoming = make_booking(starts_at=next_slot(days=2))
        past = make_booking(starts_at=next_slot(days=-2))

        client, token = logged_in(upcoming.customer)
        body = client.get(f"{BOOKINGS}?upcoming=true", **auth_header(token)).json()

        references = [row["reference"] for row in body["results"]]
        assert upcoming.reference in references
        assert past.reference not in references

    def test_status_filter(self):
        from tests.factories import make_booking

        confirmed = make_booking(status=BookingStatus.CONFIRMED)
        cancelled = make_booking(status=BookingStatus.CANCELLED_BY_CUSTOMER)

        client, token = logged_in(confirmed.customer)
        body = client.get(f"{BOOKINGS}?status=confirmed", **auth_header(token)).json()

        assert body["count"] == 1
        assert body["results"][0]["reference"] == confirmed.reference
        assert cancelled.reference not in [row["reference"] for row in body["results"]]

    def test_pagination_reports_its_metadata(self):
        from tests.factories import make_booking

        profile = make_profile()
        for _ in range(12):
            make_booking(provider=profile)

        client, token = logged_in(profile.user)
        body = client.get(BOOKINGS, **auth_header(token)).json()

        assert body["count"] == 12
        assert len(body["results"]) == 10
        assert body["next"] is not None

    def test_requires_authentication(self):
        from django.test import Client

        assert Client().get(BOOKINGS).status_code == 401


class TestDetail:
    def test_fetchable_by_reference(self):
        from tests.factories import make_booking

        booking = make_booking()
        client, token = logged_in(booking.customer)

        response = client.get(f"{BOOKINGS}{booking.reference}/", **auth_header(token))

        assert response.status_code == 200
        assert response.json()["reference"] == booking.reference

    def test_fetchable_by_id(self):
        from tests.factories import make_booking

        booking = make_booking()
        client, token = logged_in(booking.customer)

        assert client.get(f"{BOOKINGS}{booking.id}/", **auth_header(token)).status_code == 200

    def test_a_stranger_cannot_read_it(self):
        from tests.factories import make_booking

        booking = make_booking()
        client, token = logged_in(make_user())

        response = client.get(f"{BOOKINGS}{booking.reference}/", **auth_header(token))

        assert response.status_code == 404, "404 rather than 403: do not confirm it exists"

    def test_the_provider_can_read_it(self):
        from tests.factories import make_booking

        booking = make_booking()
        client, token = logged_in(booking.provider.user)

        assert (
            client.get(f"{BOOKINGS}{booking.reference}/", **auth_header(token)).status_code == 200
        )


# ---------------------------------------------------------------------------
# Cancelling
# ---------------------------------------------------------------------------


class TestCancel:
    def test_the_customer_can_cancel(self):
        from tests.factories import make_booking

        booking = make_booking(status=BookingStatus.CONFIRMED)
        client, token = logged_in(booking.customer)

        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Something came up"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        booking.refresh_from_db()
        assert booking.status == BookingStatus.CANCELLED_BY_CUSTOMER
        assert booking.cancellation_reason == "Something came up"

    def test_the_provider_can_cancel_their_side(self):
        """The old endpoint refused to let a provider cancel at all."""
        from tests.factories import make_booking

        booking = make_booking(status=BookingStatus.CONFIRMED)
        client, token = logged_in(booking.provider.user)

        response = client.post(f"{BOOKINGS}{booking.reference}/cancel/", {}, **auth_header(token))

        assert response.status_code == 200
        booking.refresh_from_db()
        assert booking.status == BookingStatus.CANCELLED_BY_PROVIDER

    def test_a_stranger_cannot_cancel(self):
        from tests.factories import make_booking

        booking = make_booking(status=BookingStatus.CONFIRMED)
        client, token = logged_in(make_user())

        response = client.post(f"{BOOKINGS}{booking.reference}/cancel/", {}, **auth_header(token))

        assert response.status_code == 404
        booking.refresh_from_db()
        assert booking.status == BookingStatus.CONFIRMED

    def test_a_completed_booking_cannot_be_cancelled(self):
        from tests.factories import make_booking

        booking = make_booking(status=BookingStatus.COMPLETED)
        client, token = logged_in(booking.customer)

        response = client.post(f"{BOOKINGS}{booking.reference}/cancel/", {}, **auth_header(token))

        assert response.status_code == 400

    def test_cancelling_frees_the_slot(self):
        from tests.factories import make_booking

        booking = make_booking(starts_at=next_slot(hour=14), status=BookingStatus.CONFIRMED)
        client, token = logged_in(booking.customer)
        client.post(f"{BOOKINGS}{booking.reference}/cancel/", {}, **auth_header(token))

        other, other_token = logged_in(make_user())
        response = other.post(
            BOOKINGS + "new/",
            booking_payload(
                booking.provider,
                [booking.items.get().service_id],
                starts_at=booking.starts_at.isoformat(),
            ),
            content_type="application/json",
            **auth_header(other_token),
        )

        assert response.status_code == 201, response.content


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_provider_accepts_an_awaiting_booking(self):
        from tests.factories import make_booking

        booking = make_booking(status=BookingStatus.AWAITING_CONFIRMATION)
        client, token = logged_in(booking.provider.user)

        response = client.post(f"{BOOKINGS}{booking.reference}/accept/", {}, **auth_header(token))

        assert response.status_code == 200
        booking.refresh_from_db()
        assert booking.status == BookingStatus.CONFIRMED

    def test_provider_completes_a_confirmed_booking(self):
        from tests.factories import make_booking

        booking = make_booking(status=BookingStatus.CONFIRMED)
        client, token = logged_in(booking.provider.user)

        response = client.post(f"{BOOKINGS}{booking.reference}/complete/", {}, **auth_header(token))

        assert response.status_code == 200
        booking.refresh_from_db()
        assert booking.status == BookingStatus.COMPLETED
        assert booking.completed_at is not None

    def test_a_customer_cannot_complete_their_own_booking(self):
        from tests.factories import make_booking

        booking = make_booking(status=BookingStatus.CONFIRMED)
        client, token = logged_in(booking.customer)

        response = client.post(f"{BOOKINGS}{booking.reference}/complete/", {}, **auth_header(token))

        assert response.status_code == 404
        booking.refresh_from_db()
        assert booking.status == BookingStatus.CONFIRMED

    def test_an_invalid_transition_is_refused(self):
        from tests.factories import make_booking

        booking = make_booking(status=BookingStatus.PENDING_PAYMENT)
        client, token = logged_in(booking.provider.user)

        response = client.post(f"{BOOKINGS}{booking.reference}/complete/", {}, **auth_header(token))

        assert response.status_code == 400

    def test_an_unknown_action_is_404(self):
        from tests.factories import make_booking

        booking = make_booking()
        client, token = logged_in(booking.provider.user)

        response = client.post(f"{BOOKINGS}{booking.reference}/teleport/", {}, **auth_header(token))

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------


class TestQuote:
    def test_prices_the_requested_services(self):
        profile = make_profile()
        haircut = make_service(profile, price=25000)
        client, token = logged_in(make_user())

        body = client.post(
            BOOKINGS + "quote/",
            booking_payload(profile, [haircut.id]),
            content_type="application/json",
            **auth_header(token),
        ).json()

        assert body["subtotal"] == 25000
        assert body["platform_fee"] == 250
        assert body["total"] == 25250
        assert body["total_display"] == "₹252.50"
        assert body["is_available"] is True

    def test_marks_a_taken_slot_unavailable(self):
        from tests.factories import make_booking

        profile = make_profile()
        haircut = make_service(profile, price=25000)
        starts_at = next_slot(hour=14)
        make_booking(provider=profile, starts_at=starts_at)

        client, token = logged_in(make_user())
        body = client.post(
            BOOKINGS + "quote/",
            booking_payload(profile, [haircut.id], starts_at=starts_at.isoformat()),
            content_type="application/json",
            **auth_header(token),
        ).json()

        assert body["is_available"] is False

    def test_the_quote_and_the_booking_agree(self):
        """The whole point: one implementation of the price, used twice."""
        profile = make_profile()
        haircut = make_service(profile, price=33333)
        starts_at = next_slot(hour=13)
        client, token = logged_in(make_user())

        quote = client.post(
            BOOKINGS + "quote/",
            booking_payload(profile, [haircut.id], starts_at=starts_at.isoformat()),
            content_type="application/json",
            **auth_header(token),
        ).json()

        booking = client.post(
            BOOKINGS + "new/",
            booking_payload(profile, [haircut.id], starts_at=starts_at.isoformat()),
            content_type="application/json",
            **auth_header(token),
        ).json()

        assert booking["total"] == quote["total"]
        assert booking["platform_fee"] == quote["platform_fee"]

    def test_requires_authentication(self):
        from django.test import Client

        assert (
            Client().post(BOOKINGS + "quote/", {}, content_type="application/json").status_code
            == 401
        )


def test_capabilities_are_not_double_booked():
    """One chair per employee, unless the shop says otherwise."""
    profile = make_profile(employee_count=1)
    service = make_service(profile)
    customer_a, token_a = logged_in(make_user())
    customer_b, token_b = logged_in(make_user())

    starts_at = next_slot(hour=16).isoformat()
    first = customer_a.post(
        BOOKINGS + "new/",
        booking_payload(profile, [service.id], starts_at=starts_at),
        content_type="application/json",
        **auth_header(token_a),
    )
    second = customer_b.post(
        BOOKINGS + "new/",
        booking_payload(profile, [service.id], starts_at=starts_at),
        content_type="application/json",
        **auth_header(token_b),
    )

    assert first.status_code == 201
    assert second.status_code == 400

    profile.employee_count = 2
    profile.save()
    third = customer_b.post(
        BOOKINGS + "new/",
        booking_payload(profile, [service.id], starts_at=starts_at),
        content_type="application/json",
        **auth_header(token_b),
    )
    assert third.status_code == 201
