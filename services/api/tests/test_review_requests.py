"""Asking for the review, and taking one down.

Reviews are already tied to completed bookings, so the trust signal is right.
Nobody was asking, which is the other half of it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from reviews.models import Review, ReviewRequest, can_be_requested_removed
from reviews.requests import due, send_requests
from tests.factories import (
    auth_header,
    logged_in,
    make_profile,
    make_provider_user,
    make_user,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
REVIEWS = f"{V1}/reviews/"

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def a_completed(days_ago: float = 2):
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner, display_name="Sharp Cuts Studio")
    customer = make_user(_next_name("customer"))
    completed_at = timezone.now() - timedelta(days=days_ago)

    booking = Booking.objects.create(
        customer=customer,
        provider=profile,
        starts_at=completed_at - timedelta(hours=1),
        ends_at=completed_at,
        completed_at=completed_at,
        status=BookingStatus.COMPLETED,
        subtotal=20000,
        platform_fee=200,
        total=20200,
    )
    return customer, profile, booking


def a_token(user) -> None:
    from accounts.models import PushToken

    PushToken.objects.create(
        user=user, token=f"ExponentPushToken[{user.pk}-{_next_name('t')}]", active=True
    )


class TestWhoGetsAsked:
    def test_a_booking_a_day_old_is_asked(self):
        _customer, _profile, booking = a_completed(days_ago=2)
        assert [b.pk for b in due()] == [booking.pk]

    def test_one_hours_after_is_not(self):
        """Nobody has an opinion yet."""
        a_completed(days_ago=1 / 24)
        assert due() == []

    def test_two_months_after_is_not(self):
        """By then it is about the platform, not the haircut."""
        a_completed(days_ago=70)
        assert due() == []

    def test_an_uncancelled_booking_is_never_asked(self):
        _customer, _profile, booking = a_completed()
        Booking.objects.filter(pk=booking.pk).update(status=BookingStatus.CANCELLED_BY_CUSTOMER)
        assert due() == []

    def test_somebody_who_already_reviewed_is_not_asked_again(self):
        """Asking for something they have done is just nagging."""
        customer, profile, booking = a_completed()
        Review.objects.create(
            provider=profile, customer=customer, booking=booking, rating=5, comment="Good"
        )
        assert due() == []


class TestAskingOnce:
    def test_a_completed_booking_is_nudged_exactly_once(self):
        customer, _profile, booking = a_completed()
        a_token(customer)

        first = send_requests()
        assert first["sent"] == 1

        second = send_requests()
        assert second["sent"] == 0
        assert second["already_asked"] == 1
        assert ReviewRequest.objects.filter(booking=booking).count() == 1

    def test_and_still_once_tomorrow(self):
        customer, _profile, _booking = a_completed()
        a_token(customer)

        send_requests()
        send_requests()
        send_requests()

        assert ReviewRequest.objects.count() == 1

    def test_somebody_with_no_device_is_not_recorded_as_asked(self):
        """Otherwise a failed push means they are never asked at all."""
        _customer, _profile, _booking = a_completed()

        counts = send_requests()

        assert counts["no_tokens"] == 1
        assert not ReviewRequest.objects.exists()


def _a_png() -> bytes:
    """A real, valid 1x1 PNG.

    The serializer rejects a file that is not an image, which is the correct
    behaviour — so the test needs an actual image rather than bytes that look
    like one.
    """
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


class TestPhotos:
    def test_a_review_can_carry_a_photo(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        customer, profile, booking = a_completed()
        client, token = logged_in(customer)

        response = client.post(
            f"{REVIEWS}new/",
            {
                "provider": profile.pk,
                "rating": 5,
                "comment": "Exactly what I asked for.",
                "booking": booking.pk,
                "photo": SimpleUploadedFile("cut.png", _a_png(), content_type="image/png"),
            },
            **auth_header(token),
        )

        assert response.status_code == 201, response.data
        review = Review.objects.get()
        assert review.photo.name.endswith(".png")
        assert response.data["photo"].endswith(".png")

    def test_a_review_without_one_still_works(self):
        customer, profile, booking = a_completed()
        client, token = logged_in(customer)

        response = client.post(
            f"{REVIEWS}new/",
            {"provider": profile.pk, "rating": 4, "booking": booking.pk},
            **auth_header(token),
        )
        assert response.status_code == 201, response.data
        assert not Review.objects.get().photo


class TestAskingForRemoval:
    def test_abuse_can_be_reported(self):
        _customer, profile, booking = a_completed()
        owner = profile.user
        Review.objects.create(
            provider=profile,
            customer=booking.customer,
            booking=booking,
            rating=1,
            comment="Abuse and harassment",
        )
        client, token = logged_in(owner)

        response = client.post(
            f"{REVIEWS}{Review.objects.get().pk}/request-removal/",
            {"reason": "This is harassment and abuse, not a review of us."},
            **auth_header(token),
        )

        assert response.status_code == 200, response.data
        assert Review.objects.get().removal_requested_at is not None

    def test_being_rated_badly_is_not_a_reason(self):
        """A provider who could wave a review away would have no reason to keep
        the rating honest."""
        _customer, profile, booking = a_completed()
        owner = profile.user
        Review.objects.create(
            provider=profile, customer=booking.customer, booking=booking, rating=1, comment="Rude"
        )
        client, token = logged_in(owner)

        response = client.post(
            f"{REVIEWS}{Review.objects.get().pk}/request-removal/",
            {"reason": "They said something we did not like."},
            **auth_header(token),
        )

        assert response.status_code >= 400
        assert "abuse" in str(response.data).lower()
        assert Review.objects.get().removal_requested_at is None

    def test_the_rule_is_one_place_not_a_decision_per_view(self):
        def as_(reason: str):
            return type("R", (), {"removal_requested_reason": reason})()

        assert can_be_requested_removed("spam") is True
        assert can_be_requested_removed("harassment") is True
        assert can_be_requested_removed("they were rude") is False
        assert can_be_requested_removed("") is False
        # And the property on the model delegates to it, rather than repeating it.
        real = Review(provider=None, customer=None, rating=5, comment="")
        real.removal_requested_reason = "abuse"
        assert real.can_be_requested_removed is True

    def test_you_cannot_report_someone_elses_review(self):
        _customer, profile, booking = a_completed()
        other_owner = make_provider_user(_next_name("other"))
        make_profile(other_owner)
        Review.objects.create(
            provider=profile, customer=booking.customer, booking=booking, rating=1
        )
        client, token = logged_in(other_owner)

        response = client.post(
            f"{REVIEWS}{Review.objects.get().pk}/request-removal/",
            {"reason": "abuse"},
            **auth_header(token),
        )
        assert response.status_code in (403, 404)

    def test_the_review_stays_up_pending_moderation(self):
        _customer, profile, booking = a_completed()
        owner = profile.user
        review = Review.objects.create(
            provider=profile, customer=booking.customer, booking=booking, rating=1, comment="Abuse"
        )
        client, token = logged_in(owner)

        client.post(
            f"{REVIEWS}{review.pk}/request-removal/", {"reason": "abuse"}, **auth_header(token)
        )

        review.refresh_from_db()
        assert review.is_hidden is False


class TestTheProviderHears:
    def test_a_provider_is_told_when_a_review_arrives(self, monkeypatch):
        sent = []
        monkeypatch.setattr("reviews.views.notify_provider", lambda review: sent.append(review))

        customer, profile, booking = a_completed()
        client, token = logged_in(customer)
        client.post(
            f"{REVIEWS}new/",
            {"provider": profile.pk, "rating": 5, "booking": booking.pk},
            **auth_header(token),
        )

        assert len(sent) == 1


class TestTheTask:
    def test_it_is_scheduled(self):
        from config.celery import app

        scheduled = {conf["task"] for conf in app.conf.beat_schedule.values()}
        assert "bookings.reminders.request_reviews" in scheduled

    def test_it_runs(self, monkeypatch):
        import reviews.requests as requests_module

        sent = []
        monkeypatch.setattr(requests_module, "deliver_push", lambda tokens, **kw: sent.append(kw))
        customer, _profile, _booking = a_completed()
        a_token(customer)

        counts = requests_module.send_requests()

        assert counts["sent"] == 1
        assert len(sent) == 1


class TestThePhotoIsActuallyOnThePage:
    """A review with a photo that renders on the shop page.

    The API test above asserted the upload was stored and returned. It never
    looked at the page - and the page did not render the photo at all, so the
    acceptance criterion was met in a JSON response nobody reads.
    """

    def test_it_shows_on_the_public_shop_page(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        customer, profile, booking = a_completed()
        client, token = logged_in(customer)
        client.post(
            f"{REVIEWS}new/",
            {
                "provider": profile.pk,
                "rating": 5,
                "comment": "Exactly what I asked for.",
                "booking": booking.pk,
                "photo": SimpleUploadedFile("cut.png", _a_png(), content_type="image/png"),
            },
            **auth_header(token),
        )

        page = client.get(f"/shops/{profile.slug}/")

        assert page.status_code == 200
        html = page.content.decode()
        assert "Exactly what I asked for" in html, "the review is not on the page at all"
        assert Review.objects.get().photo.url in html, "the review is there but the photo is not"

    def test_a_page_without_one_is_unaffected(self):
        _customer, profile, _booking = a_completed()
        client, _token = logged_in(_customer)

        page = client.get(f"/shops/{profile.slug}/")

        assert page.status_code == 200
        assert 'class="review-photo"' not in page.content.decode()


class TestAnOptOutThatIsActuallyAnOptOut:
    """Review requests have to stop when somebody says stop.

    The check required three categories to be off at once, one of which the
    server forces back on - so it could never be false, and nobody who turned
    notifications off was ever spared a review request.
    """

    def _opts_out_of_reminders(self, user) -> None:
        from accounts.models import NotificationKey, NotificationPreference

        NotificationPreference.objects.update_or_create(
            user=user,
            key=NotificationKey.BOOKING_REMINDERS,
            defaults={"enabled": False},
        )

    def test_somebody_who_opted_out_is_left_alone(self):
        from reviews.requests import _wants

        customer, _profile, _booking = a_completed()
        self._opts_out_of_reminders(customer)

        assert _wants(customer) is False

    def test_the_default_is_still_to_ask(self):
        from reviews.requests import _wants

        customer, _profile, _booking = a_completed()

        assert _wants(customer) is True
