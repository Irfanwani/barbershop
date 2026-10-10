"""Tests for ``/api/v1/reviews/``."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bookings.models import BookingStatus
from reviews.models import Review
from tests.factories import (
    auth_header,
    logged_in,
    make_booking,
    make_profile,
    make_review,
    make_user,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
REVIEWS = f"{V1}/reviews/"


def review_payload(provider_id: int, **overrides) -> dict:
    payload = {"provider": provider_id, "rating": 5, "comment": "Great cut"}
    payload.update(overrides)
    return payload


class TestCreate:
    def test_a_customer_can_review(self):
        client, token = logged_in(make_user())
        profile = make_profile()

        response = client.post(
            REVIEWS + "new/",
            review_payload(profile.id),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 201, response.content
        assert Review.objects.count() == 1

    def test_the_provider_rating_is_recalculated(self):
        """The old endpoint never updated the aggregate, so ratings were fiction."""
        client, token = logged_in(make_user())
        profile = make_profile()

        client.post(
            REVIEWS + "new/",
            review_payload(profile.id, rating=4),
            content_type="application/json",
            **auth_header(token),
        )

        profile.refresh_from_db()
        assert profile.rating_average == Decimal("4.00")
        assert profile.rating_count == 1

    @pytest.mark.parametrize("rating", [0, 6, 11, -1])
    def test_a_rating_outside_one_to_five_is_refused(self, rating):
        client, token = logged_in(make_user())
        profile = make_profile()

        response = client.post(
            REVIEWS + "new/",
            review_payload(profile.id, rating=rating),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert "rating" in response.json()["error"]["details"]

    def test_can_be_attached_to_a_completed_booking(self):
        profile = make_profile()
        booking = make_booking(provider=profile, status=BookingStatus.COMPLETED)
        client, token = logged_in(booking.customer)

        response = client.post(
            REVIEWS + "new/",
            review_payload(profile.id, booking=booking.id),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 201, response.content
        assert response.json()["booking"] == booking.id

    def test_cannot_review_someone_elses_booking(self):
        profile = make_profile()
        booking = make_booking(provider=profile, status=BookingStatus.COMPLETED)
        client, token = logged_in(make_user())

        response = client.post(
            REVIEWS + "new/",
            review_payload(profile.id, booking=booking.id),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_cannot_review_a_booking_still_to_happen(self):
        profile = make_profile()
        booking = make_booking(provider=profile, status=BookingStatus.CONFIRMED)
        client, token = logged_in(booking.customer)

        response = client.post(
            REVIEWS + "new/",
            review_payload(profile.id, booking=booking.id),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert "over" in response.json()["error"]["message"]

    def test_one_review_per_booking(self):
        profile = make_profile()
        booking = make_booking(provider=profile, status=BookingStatus.COMPLETED)
        client, token = logged_in(booking.customer)
        payload = review_payload(profile.id, booking=booking.id)

        client.post(
            REVIEWS + "new/", payload, content_type="application/json", **auth_header(token)
        )
        second = client.post(
            REVIEWS + "new/", payload, content_type="application/json", **auth_header(token)
        )

        assert second.status_code == 400

    def test_reviewing_an_unknown_provider(self):
        client, token = logged_in(make_user())

        response = client.post(
            REVIEWS + "new/",
            review_payload(999999),
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_requires_authentication(self):
        from django.test import Client

        assert (
            Client().post(REVIEWS + "new/", {}, content_type="application/json").status_code == 401
        )


class TestList:
    def test_lists_reviews_for_a_provider_with_a_summary(self):
        profile = make_profile()
        make_review(provider=profile, rating=5)
        make_review(provider=profile, rating=4)
        client, token = logged_in(make_user())

        body = client.get(f"{REVIEWS}?provider={profile.id}", **auth_header(token)).json()

        assert body["count"] == 2
        assert body["summary"] == {"average": 4.5, "total": 2}

    def test_can_list_your_own(self):
        mine = make_review(rating=5)
        make_review(rating=1)
        client, token = logged_in(mine.customer)

        body = client.get(f"{REVIEWS}?mine=true", **auth_header(token)).json()

        assert body["count"] == 1
        assert body["results"][0]["rating"] == 5

    def test_filters_by_rating(self):
        profile = make_profile()
        make_review(provider=profile, rating=1)
        make_review(provider=profile, rating=5)
        client, token = logged_in(make_user())

        body = client.get(f"{REVIEWS}?provider={profile.id}&rating=1", **auth_header(token)).json()

        assert body["count"] == 1
        assert body["results"][0]["rating"] == 1

    def test_hidden_reviews_are_not_shown(self):
        profile = make_profile()
        make_review(provider=profile, comment="spam", is_hidden=True)
        client, token = logged_in(make_user())

        assert (
            client.get(f"{REVIEWS}?provider={profile.id}", **auth_header(token)).json()["count"]
            == 0
        )

    def test_review_does_not_leak_the_customers_email(self):
        reviewer = make_user("reviewer", email="reviewer@example.com")
        review = make_review(customer=reviewer)
        client, token = logged_in(make_user())

        body = client.get(f"{REVIEWS}?provider={review.provider_id}", **auth_header(token)).json()

        assert "reviewer@example.com" not in str(body)
        assert body["results"][0]["customer_display_name"] == "reviewer"


class TestDetailAndDelete:
    def test_read_one(self):
        review = make_review()
        client, token = logged_in(make_user())

        assert client.get(f"{REVIEWS}{review.id}/", **auth_header(token)).status_code == 200

    def test_the_author_can_delete_their_own(self):
        review = make_review()
        client, token = logged_in(review.customer)

        response = client.delete(f"{REVIEWS}{review.id}/", **auth_header(token))

        assert response.status_code == 204
        assert not Review.objects.filter(pk=review.pk).exists()

    def test_someone_else_cannot_delete_it(self):
        review = make_review()
        client, token = logged_in(make_user())

        response = client.delete(f"{REVIEWS}{review.id}/", **auth_header(token))

        assert response.status_code == 403
        assert Review.objects.filter(pk=review.pk).exists()

    def test_staff_can_delete_any(self):
        review = make_review()
        staff = make_user("moderator", is_staff=True)
        client, token = logged_in(staff)

        assert client.delete(f"{REVIEWS}{review.id}/", **auth_header(token)).status_code == 204

    def test_hidden_reviews_are_not_readable(self):
        review = make_review(is_hidden=True)
        client, token = logged_in(make_user())

        assert client.get(f"{REVIEWS}{review.id}/", **auth_header(token)).status_code == 404


class TestReply:
    def test_a_provider_can_reply(self):
        review = make_review()
        client, token = logged_in(review.provider.user)

        response = client.post(
            f"{REVIEWS}{review.id}/reply/",
            {"provider_reply": "Thanks for coming in!"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        review.refresh_from_db()
        assert review.provider_reply == "Thanks for coming in!"
        assert review.replied_at is not None

    def test_a_provider_cannot_reply_to_another_shop(self):
        review = make_review()
        other = make_profile(display_name="Someone Else")
        client, token = logged_in(other.user)

        response = client.post(
            f"{REVIEWS}{review.id}/reply/",
            {"provider_reply": "Not mine"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 404

    def test_a_customer_cannot_reply(self):
        review = make_review()
        client, token = logged_in(review.customer)

        response = client.post(
            f"{REVIEWS}{review.id}/reply/",
            {"provider_reply": "I am the customer"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 403
