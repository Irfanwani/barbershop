"""Filling a freed slot from the waitlist.

When a slot frees, it sits empty. The entire niche is built on not doing that,
and every claim made about this — "first to reply gets the slot", "your
waitlist gets notified instantly" — is a promise about what happens in the
seconds between a cancellation and a reply. These tests are about those
seconds, because that is where all of it can quietly go wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest
from django.utils import timezone

from bookings.models import Booking, SlotHold, WaitlistEntry, WaitlistOffer
from bookings.waitlist import (
    accept_offer,
    decline_offer,
    expire_offers,
    offer_freed_slot,
    slot_from_booking,
)
from providers.models import Staff
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
    """Unique usernames.

    Most tests need two or three people, and a duplicate username is an
    IntegrityError that has nothing to do with what is being checked.
    """
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


def a_shop():
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner, display_name="Sharp Cuts Studio")
    service = make_service(profile, price=20000, duration_minutes=30)
    return owner, profile, service


def in_two_days(hour: int = 10):
    day = timezone.localtime() + timedelta(days=2)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0)


def book(session: Session, profile, service, starts_at) -> Booking:
    response = session.client.post(
        f"{V1}/bookings/new/",
        {
            "provider": profile.pk,
            "services": [service.pk],
            "starts_at": starts_at.isoformat(),
        },
        **session.auth(),
    )
    assert response.status_code == 201, response.data
    return Booking.objects.get(reference=response.data["reference"])


def join(session: Session, profile, service, ends_at, *, staff=None, starts_at=None):
    payload = {
        "provider": profile.pk,
        "service": service.pk,
        # A second from now: a window that has already begun is refused, which
        # is the right rule but not what "any time soon" means here.
        "window_start": (starts_at or timezone.now() + timedelta(seconds=5)).isoformat(),
        "window_end": ends_at.isoformat(),
    }
    if staff is not None:
        payload["staff"] = staff.pk
    return session.client.post(f"{V1}/bookings/waitlist/", payload, **session.auth())


def cancel(session: Session, booking: Booking):
    response = session.client.post(
        f"{V1}/bookings/{booking.reference}/cancel/", {}, **session.auth()
    )
    assert response.status_code == 200, response.data
    return response


@dataclass
class Scene:
    """A shop, a slot that is about to be freed, and people waiting for it."""

    profile: Any
    service: Any
    starts_at: datetime
    waiting: list
    booker: Session
    booking: Booking

    def free(self):
        return cancel(self.booker, self.booking)

    def offers(self, status: str | None = "pending") -> list[WaitlistOffer]:
        """Offers, by default the ones still live.

        A declined or expired offer is history, and counting it as if it were
        live makes the next person in line look un-notified.
        """
        queryset = WaitlistOffer.objects.select_related("entry").order_by("pk")
        return list(queryset.filter(status=status) if status else queryset)


def scene(waiters: int = 1, *, staff=None, window_ends=None, shop=None) -> Scene:
    _owner, profile, service = shop or a_shop()
    starts_at = in_two_days()
    ends = window_ends or starts_at + timedelta(days=1)

    people = []
    for index in range(waiters):
        session = a_session(f"waiter{index}")
        response = join(session, profile, service, ends, staff=staff)
        assert response.status_code == 201, response.data
        people.append(session)

    booker = a_session("booker")
    return Scene(
        profile=profile,
        service=service,
        starts_at=starts_at,
        waiting=people,
        booker=booker,
        booking=book(booker, profile, service, starts_at),
    )


class TestJoining:
    def test_a_customer_can_join(self):
        _owner, profile, service = a_shop()
        customer = a_session("joiner")

        response = join(customer, profile, service, in_two_days() + timedelta(days=1))
        assert response.status_code == 201, response.data
        assert response.data["provider_name"] == "Sharp Cuts Studio"
        assert response.data["status"] == "waiting"

    def test_a_window_that_ends_before_it_starts_is_refused(self):
        _owner, profile, service = a_shop()
        customer = a_session("backwards")

        response = customer.client.post(
            f"{V1}/bookings/waitlist/",
            {
                "provider": profile.pk,
                "service": service.pk,
                "window_start": in_two_days().isoformat(),
                "window_end": (in_two_days() - timedelta(days=1)).isoformat(),
            },
            **customer.auth(),
        )
        assert response.status_code == 400

    def test_a_window_that_already_started_is_refused(self):
        _owner, profile, service = a_shop()
        customer = a_session("yesterday")

        response = customer.client.post(
            f"{V1}/bookings/waitlist/",
            {
                "provider": profile.pk,
                "service": service.pk,
                "window_start": (timezone.now() - timedelta(days=1)).isoformat(),
                "window_end": in_two_days().isoformat(),
            },
            **customer.auth(),
        )
        assert response.status_code == 400

    def test_joining_twice_is_refused(self):
        """Otherwise one person takes two offers for the same freed slot."""
        _owner, profile, service = a_shop()
        customer = a_session("double")
        ends = in_two_days() + timedelta(days=1)

        assert join(customer, profile, service, ends).status_code == 201
        assert join(customer, profile, service, ends).status_code == 400

    def test_a_service_from_another_shop_is_refused(self):
        _owner, profile, _service = a_shop()
        _owner2, _profile2, other_service = a_shop()

        response = join(a_session("elsewhere"), profile, other_service, in_two_days())
        assert response.status_code == 400

    def test_you_see_your_own_entries_and_nobody_elses(self):
        _owner, profile, service = a_shop()
        mine = a_session("mine")
        join(mine, profile, service, in_two_days() + timedelta(days=1))

        theirs = a_session("stranger")

        assert len(mine.client.get(f"{V1}/bookings/waitlist/", **mine.auth()).data) == 1
        assert theirs.client.get(f"{V1}/bookings/waitlist/", **theirs.auth()).data == []


class TestAFreedSlotIsOffered:
    def test_cancelling_offers_the_slot_to_someone_waiting(self):
        given = scene(waiters=1)
        given.free()

        offers = given.offers()
        assert len(offers) == 1
        assert offers[0].status == "pending"
        assert offers[0].entry.status == "offered"

    def test_the_first_to_join_is_offered_first(self):
        given = scene(waiters=3)
        first, second, third = [person.user_id for person in given.waiting]
        given.free()

        offers = given.offers()
        assert len(offers) == 1
        assert offers[0].entry.customer_id == first
        assert offers[0].entry.customer_id != second
        assert offers[0].entry.customer_id != third

    def test_only_one_person_is_offered_at_a_time(self):
        given = scene(waiters=3)
        given.free()

        assert len(given.offers()) == 1

    def test_nobody_waiting_leaves_the_slot_public(self):
        """Not a failure. It is what happens most of the time."""
        _owner, profile, service = a_shop()
        starts_at = in_two_days()
        booker = a_session("booker")
        booking = book(booker, profile, service, starts_at)

        cancel(booker, booking)

        assert WaitlistOffer.objects.count() == 0
        assert SlotHold.objects.count() == 0

    def test_you_are_not_offered_your_own_freed_slot(self):
        _owner, profile, service = a_shop()
        starts_at = in_two_days()
        mine = a_session("mine")
        assert join(mine, profile, service, starts_at + timedelta(days=1)).status_code == 201
        booking = book(mine, profile, service, starts_at)

        cancel(mine, booking)

        assert WaitlistOffer.objects.count() == 0

    def test_the_held_slot_is_not_publicly_bookable(self):
        """The seconds between offer and reply belong to one person."""
        given = scene(waiters=1)
        given.free()

        assert SlotHold.objects.filter(provider=given.profile).count() == 1

        # The shop has one chair and it is being held, so an overlapping slot
        # offers nothing even though no booking exists for it any more.
        overlapping = given.starts_at + timedelta(minutes=15)
        response = a_session("sneaky").client.post(
            f"{V1}/bookings/new/",
            {
                "provider": given.profile.pk,
                "services": [given.service.pk],
                "starts_at": overlapping.isoformat(),
            },
            **a_session("sneaky").auth(),
        )
        assert response.status_code >= 400

    def test_a_window_that_does_not_cover_the_slot_gets_nothing(self):
        """Someone who said "this afternoon" must not be woken next Tuesday."""
        given = scene(waiters=1, window_ends=timezone.now() + timedelta(hours=1))
        given.free()

        assert WaitlistOffer.objects.count() == 0
        assert SlotHold.objects.count() == 0

    def test_someone_waiting_for_one_barber_is_not_offered_another(self):
        _owner, profile, service = a_shop()
        ravi = Staff.objects.create(provider=profile, name="Ravi")
        priya = Staff.objects.create(provider=profile, name="Priya")

        given = scene(waiters=1, staff=ravi, shop=(_owner, profile, service))
        Booking.objects.filter(pk=given.booking.pk).update(staff=priya)
        given.booking.refresh_from_db()

        assert offer_freed_slot(slot_from_booking(given.booking)) is None

    def test_someone_waiting_for_anyone_is_offered_anyone(self):
        _owner, profile, service = a_shop()
        priya = Staff.objects.create(provider=profile, name="Priya")

        given = scene(waiters=1, shop=(_owner, profile, service))
        Booking.objects.filter(pk=given.booking.pk).update(staff=priya)
        given.booking.refresh_from_db()

        assert offer_freed_slot(slot_from_booking(given.booking)) is not None


class TestResponding:
    def test_accepting_creates_the_booking(self):
        given = scene(waiters=1)
        given.free()
        offer = given.offers()[0]

        response = given.waiting[0].client.post(
            f"{V1}/bookings/waitlist/offers/{offer.pk}/accept/", {}, **given.waiting[0].auth()
        )

        assert response.status_code == 201, response.data
        # Refreshed: `offer` was read before the call that changed it.
        assert WaitlistEntry.objects.get(pk=offer.entry_id).status == "booked"

    def test_accepting_releases_the_hold(self):
        given = scene(waiters=1)
        given.free()
        offer = given.offers()[0]

        accept_offer(offer)

        assert SlotHold.objects.count() == 0

    def test_declining_passes_it_to_the_next_person(self):
        given = scene(waiters=2)
        first, second = given.waiting
        given.free()
        first_offer = given.offers()[0]

        response = first.client.post(
            f"{V1}/bookings/waitlist/offers/{first_offer.pk}/decline/", {}, **first.auth()
        )

        assert response.status_code == 200
        assert response.data["passed_on"] is True

        pending = given.offers()
        assert len(pending) == 1
        assert pending[0].entry.customer_id == second.user_id

    def test_declining_does_not_take_you_off_the_waitlist(self):
        """They said no to this minute; they may still want the next one."""
        given = scene(waiters=1)
        given.free()
        offer = given.offers()[0]

        decline_offer(offer)

        assert WaitlistEntry.objects.get(pk=offer.entry_id).status == "waiting"

    def test_declining_with_nobody_left_returns_the_slot_to_the_public(self):
        given = scene(waiters=1)
        given.free()
        offer = given.offers()[0]

        response = given.waiting[0].client.post(
            f"{V1}/bookings/waitlist/offers/{offer.pk}/decline/", {}, **given.waiting[0].auth()
        )

        assert response.status_code == 200
        assert response.data["passed_on"] is False
        assert SlotHold.objects.count() == 0

    def test_leaving_releases_the_slot(self):
        given = scene(waiters=1)
        given.free()
        entry = WaitlistEntry.objects.get()

        response = given.waiting[0].client.delete(
            f"{V1}/bookings/waitlist/{entry.pk}/", **given.waiting[0].auth()
        )

        assert response.status_code == 204
        assert SlotHold.objects.count() == 0
        assert WaitlistEntry.objects.get(pk=entry.pk).status == "left"

    def test_you_cannot_take_someone_elses_offer(self):
        given = scene(waiters=1)
        given.free()
        offer = given.offers()[0]
        thief = a_session("thief")

        response = thief.client.post(
            f"{V1}/bookings/waitlist/offers/{offer.pk}/accept/", {}, **thief.auth()
        )
        assert response.status_code == 404


class TestOffersExpire:
    def test_an_unanswered_hold_returns_the_slot_to_the_public(self):
        given = scene(waiters=1)
        given.free()
        WaitlistOffer.objects.update(expires_at=timezone.now() - timedelta(minutes=1))

        counts = expire_offers()

        assert counts["expired"] == 1
        assert SlotHold.objects.count() == 0

    def test_an_expired_hold_goes_to_the_next_person(self):
        given = scene(waiters=2)
        given.free()
        WaitlistOffer.objects.update(expires_at=timezone.now() - timedelta(minutes=1))

        counts = expire_offers()

        assert counts == {"expired": 1, "reoffered": 1}
        pending = given.offers()
        assert len(pending) == 1
        assert pending[0].status == "pending"

    def test_an_expired_hold_is_not_offered_again_to_the_same_person(self):
        """They already had their turn. Silence is not an endless queue."""
        given = scene(waiters=1)
        given.free()
        WaitlistOffer.objects.update(expires_at=timezone.now() - timedelta(minutes=1))

        expire_offers()

        assert WaitlistOffer.objects.filter(status="pending").count() == 0

    def test_accepting_an_expired_offer_is_refused(self):
        given = scene(waiters=1)
        given.free()
        offer = given.offers()[0]
        WaitlistOffer.objects.filter(pk=offer.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        offer.refresh_from_db()

        response = given.waiting[0].client.post(
            f"{V1}/bookings/waitlist/offers/{offer.pk}/accept/", {}, **given.waiting[0].auth()
        )
        assert response.status_code >= 400

    def test_an_expired_hold_stops_blocking_the_slot(self):
        """The cleanup task is a convenience; a dead worker must not cost a chair."""
        given = scene(waiters=1)
        given.free()
        WaitlistOffer.objects.update(expires_at=timezone.now() - timedelta(minutes=1))

        overlapping = given.starts_at + timedelta(minutes=15)
        session = a_session("later")
        response = session.client.post(
            f"{V1}/bookings/new/",
            {
                "provider": given.profile.pk,
                "services": [given.service.pk],
                "starts_at": overlapping.isoformat(),
            },
            **session.auth(),
        )
        assert response.status_code == 201, response.data

    def test_the_offer_list_shows_a_countdown(self):
        given = scene(waiters=1)
        given.free()

        response = given.waiting[0].client.get(
            f"{V1}/bookings/waitlist/offers/", **given.waiting[0].auth()
        )

        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]["shop_name"] == "Sharp Cuts Studio"
        assert response.data[0]["can_accept"] is True
        assert 0 < response.data[0]["seconds_left"] <= 15 * 60

    def test_an_expired_offer_is_shown_as_unclaimable(self):
        """Offering a button that will be refused is worse than not offering it."""
        given = scene(waiters=1)
        given.free()
        WaitlistOffer.objects.update(expires_at=timezone.now() - timedelta(minutes=1))

        response = given.waiting[0].client.get(
            f"{V1}/bookings/waitlist/offers/", **given.waiting[0].auth()
        )
        assert response.data[0]["can_accept"] is False
