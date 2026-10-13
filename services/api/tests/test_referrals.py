"""Referrals.

Give a credit, get a credit. Standard in the category, and the reason it is
fussier than it looks: **a referral programme is a way to mint points**, so
almost every rule here is about closing a hole rather than about generosity.

The tests that matter are the refusals. A referral that pays out correctly is
easy; one that pays out when it should not is how a loyalty balance stops
meaning anything.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from promotions import loyalty, referrals
from promotions.models import (
    LoyaltyLedgerEntry,
    Referral,
    ReferralCode,
    ReferralStatus,
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
MY_REFERRALS = f"{V1}/promotions/referrals/me/"
PROVIDER_REFERRALS = f"{V1}/promotions/referrals/provider/"

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def a_shop():
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner, display_name="Sharp Cuts Studio")
    make_service(profile, price=20000, deposit_percent=50)
    return profile


def a_slot(hours: int = 48) -> str:
    """A bookable slot, pulled inside the shop's 09:00-20:00."""
    moment = timezone.localtime() + timedelta(hours=hours)
    if moment.hour < 9:
        moment = moment.replace(hour=10)
    elif moment.hour >= 19:
        moment = moment.replace(hour=18)
    return moment.replace(minute=0, second=0, microsecond=0).isoformat()


def book(
    client,
    token,
    profile,
    service,
    *,
    referral_code: str | None = None,
    hours: int = 48,
):
    # ``hours`` varies so a test that books twice is not booking the same slot
    # twice and being refused by capacity rather than by the thing under test.
    body: dict[str, Any] = {
        "provider": profile.pk,
        "services": [service.pk],
        "starts_at": a_slot(hours),
    }
    if referral_code is not None:
        body["referral_code"] = referral_code
    return client.post(
        f"{BOOKINGS}new/",
        body,
        content_type="application/json",
        **auth_header(token),
    )


def complete(booking: Booking) -> Booking:
    Booking.objects.filter(pk=booking.pk).update(
        status=BookingStatus.COMPLETED, completed_at=timezone.now()
    )
    referrals.reward(Booking.objects.get(pk=booking.pk))
    return booking


class TestTheCode:
    def test_everyone_gets_one(self):
        customer = make_user(_next_name("customer"))
        client, token = logged_in(customer)

        response = client.get(MY_REFERRALS, **auth_header(token))

        assert response.status_code == 200
        assert response.data["code"]

    def test_it_is_the_same_one_every_time(self):
        customer = make_user(_next_name("customer"))
        client, token = logged_in(customer)

        first = client.get(MY_REFERRALS, **auth_header(token)).data["code"]
        second = client.get(MY_REFERRALS, **auth_header(token)).data["code"]

        assert first == second
        assert ReferralCode.objects.filter(customer=customer).count() == 1

    def test_two_people_never_share_one(self):
        codes = {logged_in(make_user(_next_name("c")))[1] for _ in range(5)}
        assert len(codes) == 5

    def test_there_are_no_confusable_characters_in_it(self):
        """Somebody is going to read this out over the phone.

        No zero/O, no one/I: they are the two pairs that get misheard, and a
        code that does not survive being read aloud is not a referral code.
        """
        customer = make_user(_next_name("customer"))

        code = referrals.code_for(customer).code

        assert not set("01OIl") & set(code)

    def test_nobody_elses_code_is_your_code(self):
        one = make_user(_next_name("one"))
        two = make_user(_next_name("two"))

        assert referrals.code_for(one).code != referrals.code_for(two).code


class TestSelfReferral:
    """The acceptance test: a self-referral credits nobody."""

    def test_the_database_refuses_it(self):
        """Even if some future endpoint forgets to check."""
        from django.db.utils import IntegrityError

        customer = make_user(_next_name("customer"))
        code = referrals.code_for(customer)

        with pytest.raises(IntegrityError):
            Referral.objects.create(referrer=customer, referred=customer, code=code)

    def test_and_the_code_is_rejected_at_booking(self):
        profile = a_shop()
        service = profile.services.first()
        customer = make_user(_next_name("customer"))
        client, token = logged_in(customer)
        code = referrals.code_for(customer).code

        response = book(client, token, profile, service, referral_code=code)

        # The booking still goes ahead: somebody mistyping a code at checkout
        # must not lose their slot.
        assert response.status_code == 201, response.data
        assert not Referral.objects.exists()

    def test_nobody_is_credited(self):
        profile = a_shop()
        service = profile.services.first()
        customer = make_user(_next_name("customer"))
        client, token = logged_in(customer)
        code = referrals.code_for(customer).code

        created = book(client, token, profile, service, referral_code=code)
        complete(Booking.objects.get(reference=created.data["reference"]))

        assert LoyaltyLedgerEntry.objects.filter(reason="referral").count() == 0
        assert loyalty.balance(customer).available >= 0


class TestItCreditsOnCompletionNotBooking:
    """The other half of the acceptance test."""

    def test_booking_alone_credits_nobody(self):
        profile = a_shop()
        service = profile.services.first()
        friend = make_user(_next_name("friend"))
        code = referrals.code_for(make_user(_next_name("referrer"))).code

        client, token = logged_in(friend)
        created = book(client, token, profile, service, referral_code=code)

        assert created.status_code == 201, created.data
        assert LoyaltyLedgerEntry.objects.filter(reason="referral").count() == 0
        assert Referral.objects.get().status == ReferralStatus.PENDING

    def test_completion_credits_both_sides(self):
        profile = a_shop()
        service = profile.services.first()
        referrer = make_user(_next_name("referrer"))
        friend = make_user(_next_name("friend"))
        code = referrals.code_for(referrer).code

        client, token = logged_in(friend)
        created = book(client, token, profile, service, referral_code=code)
        complete(Booking.objects.get(reference=created.data["reference"]))

        assert LoyaltyLedgerEntry.objects.filter(
            customer=referrer, reason="referral", points__gt=0
        ).exists()
        assert LoyaltyLedgerEntry.objects.filter(
            customer=friend, reason="referral", points__gt=0
        ).exists()

    def test_and_credits_them_once(self):
        """Two completed bookings, one reward.

        Somebody who was referred, did not come for six months, and then came
        twice in a row has been referred once.
        """
        profile = a_shop()
        service = profile.services.first()
        referrer = make_user(_next_name("referrer"))
        friend = make_user(_next_name("friend"))
        code = referrals.code_for(referrer).code

        client, token = logged_in(friend)
        first = book(client, token, profile, service, referral_code=code)
        complete(Booking.objects.get(reference=first.data["reference"]))

        second = book(client, token, profile, service, referral_code=code, hours=96)
        complete(Booking.objects.get(reference=second.data["reference"]))

        rewarded = LoyaltyLedgerEntry.objects.filter(customer=referrer, reason="referral")
        assert rewarded.count() == 1, "paid the referrer twice"

    def test_completing_twice_pays_out_once(self):
        """The reward is not idempotent by accident."""
        profile = a_shop()
        service = profile.services.first()
        referrer = make_user(_next_name("referrer"))
        friend = make_user(_next_name("friend"))
        code = referrals.code_for(referrer).code

        client, token = logged_in(friend)
        created = book(client, token, profile, service, referral_code=code)
        booking = Booking.objects.get(reference=created.data["reference"])
        Booking.objects.filter(pk=booking.pk).update(status=BookingStatus.COMPLETED)

        first = referrals.reward(booking)
        second = referrals.reward(booking)

        assert first.referrer_points > 0
        assert second.referrer_points == 0
        assert LoyaltyLedgerEntry.objects.filter(reason="referral").count() == 2


class TestSameAccountAbuse:
    def test_nobody_can_be_referred_twice(self):
        profile = a_shop()
        service = profile.services.first()
        first_referrer = make_user(_next_name("referrer"))
        second_referrer = make_user(_next_name("referrer"))
        friend = make_user(_next_name("friend"))

        client, token = logged_in(friend)
        book(client, token, profile, service, referral_code=referrals.code_for(first_referrer).code)
        response = book(
            client,
            token,
            profile,
            service,
            referral_code=referrals.code_for(second_referrer).code,
            hours=96,
        )

        # The booking is not blocked - a code that does not apply is not the
        # customer's problem - but only one referral is recorded.
        assert response.status_code == 201, response.data
        assert Referral.objects.filter(referred=friend).count() == 1

    def test_the_database_refuses_two_referrers_for_one_person(self):
        from django.db.utils import IntegrityError

        friend = make_user(_next_name("friend"))
        one = referrals.code_for(make_user(_next_name("referrer")))
        two = referrals.code_for(make_user(_next_name("referrer")))

        Referral.objects.create(referrer=one.customer, referred=friend, code=one)
        with pytest.raises(IntegrityError):
            Referral.objects.create(referrer=two.customer, referred=friend, code=two)

    def test_an_unknown_code_is_ignored_rather_than_an_error(self):
        """A mistyped code at checkout must not cost somebody their slot."""
        profile = a_shop()
        service = profile.services.first()
        client, token = logged_in(make_user(_next_name("friend")))

        response = book(client, token, profile, service, referral_code="NOTACODE")

        assert response.status_code == 201, response.data
        assert not Referral.objects.exists()

    def test_an_empty_code_is_fine(self):
        profile = a_shop()
        service = profile.services.first()
        client, token = logged_in(make_user(_next_name("friend")))

        response = book(client, token, profile, service, referral_code="")

        assert response.status_code == 201


class TestACancelledReferral:
    def test_it_is_not_owed_anything(self):
        profile = a_shop()
        service = profile.services.first()
        referrer = make_user(_next_name("referrer"))
        friend = make_user(_next_name("friend"))
        code = referrals.code_for(referrer).code

        client, token = logged_in(friend)
        created = book(client, token, profile, service, referral_code=code)
        booking = Booking.objects.get(reference=created.data["reference"])

        client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {},
            content_type="application/json",
            **auth_header(token),
        )

        complete(booking)
        assert not LoyaltyLedgerEntry.objects.filter(reason="referral").exists()

    def test_and_they_still_cannot_be_referred_by_somebody_else(self):
        """Deleting the record would quietly hand them a second referrer."""
        profile = a_shop()
        service = profile.services.first()
        first_referrer = make_user(_next_name("referrer"))
        second_referrer = make_user(_next_name("referrer"))
        friend = make_user(_next_name("friend"))

        client, token = logged_in(friend)
        created = book(
            client, token, profile, service, referral_code=referrals.code_for(first_referrer).code
        )
        booking = Booking.objects.get(reference=created.data["reference"])
        client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {},
            content_type="application/json",
            **auth_header(token),
        )

        book(
            client,
            token,
            profile,
            service,
            referral_code=referrals.code_for(second_referrer).code,
            hours=96,
        )

        referral = Referral.objects.get(referred=friend)
        assert referral.status == ReferralStatus.LAPSED
        assert referral.referrer == first_referrer


class TestAttribution:
    def test_it_goes_to_the_shop_that_did_the_work(self):
        """Not the shop that issued the code.

        Somebody can hand out their code and send their friend somewhere else
        entirely, and crediting the issuer would be a lie told in the ledger.
        """
        issuing_shop = a_shop()
        other_shop = a_shop()
        referrer = make_user(_next_name("referrer"))
        friend = make_user(_next_name("friend"))
        code = referrals.code_for(referrer).code

        client, token = logged_in(friend)
        created = book(client, token, other_shop, other_shop.services.first(), referral_code=code)
        complete(Booking.objects.get(reference=created.data["reference"]))

        referral = Referral.objects.get()
        assert referral.provider == other_shop
        assert referral.provider != issuing_shop

    def test_nobody_is_attributed_before_the_booking_completes(self):
        profile = a_shop()
        friend = make_user(_next_name("friend"))
        code = referrals.code_for(make_user(_next_name("referrer"))).code

        client, token = logged_in(friend)
        book(client, token, profile, profile.services.first(), referral_code=code)

        assert Referral.objects.get().provider is None


class TestTheEndpoints:
    def test_the_summary_does_not_leak_another_persons_code(self):
        friend = make_user(_next_name("friend"))
        referrer = make_user(_next_name("referrer"))
        referrals.code_for(referrer)
        client, token = logged_in(friend)

        response = client.get(MY_REFERRALS, **auth_header(token))

        assert response.status_code == 200
        assert response.data["referred_by"] is None
        assert response.data["given"] == []

    def test_the_provider_sees_what_they_won(self):
        profile = a_shop()
        referrer = make_user(_next_name("referrer"))
        friend = make_user(_next_name("friend"))
        code = referrals.code_for(referrer).code

        client, token = logged_in(friend)
        created = book(client, token, profile, profile.services.first(), referral_code=code)
        complete(Booking.objects.get(reference=created.data["reference"]))

        owner_client, owner_token = logged_in(profile.user)
        response = owner_client.get(PROVIDER_REFERRALS, **auth_header(owner_token))

        assert response.status_code == 200
        assert response.data["rewarded_count"] == 1
        assert response.data["points_earned_by_customers"] > 0

    def test_a_shop_cannot_read_another_shops_referrals(self):
        profile = a_shop()
        other = a_shop()
        friend = make_user(_next_name("friend"))
        code = referrals.code_for(make_user(_next_name("referrer"))).code

        client, token = logged_in(friend)
        created = book(client, token, profile, profile.services.first(), referral_code=code)
        complete(Booking.objects.get(reference=created.data["reference"]))

        owner_client, owner_token = logged_in(other.user)
        response = owner_client.get(PROVIDER_REFERRALS, **auth_header(owner_token))

        assert response.data["count"] == 0

    def test_a_customer_is_not_a_provider(self):
        client, token = logged_in(make_user(_next_name("customer")))

        response = client.get(PROVIDER_REFERRALS, **auth_header(token))

        assert response.status_code in (403, 404)

    def test_the_referred_person_sees_who_referred_them(self):
        profile = a_shop()
        referrer = make_user(_next_name("referrer"))
        friend = make_user(_next_name("friend"))
        code = referrals.code_for(referrer).code

        client, token = logged_in(friend)
        book(client, token, profile, profile.services.first(), referral_code=code)

        response = client.get(MY_REFERRALS, **auth_header(token))

        assert response.data["referred_by"] == referrer.display_name


class TestTheLedgerItself:
    def test_referral_points_are_points_like_any_other(self):
        """They expire, and they show up in the balance.

        A credit written anywhere other than the loyalty ledger is points
        nobody can explain, and an unexpired one is a liability the platform
        cannot plan for.
        """
        profile = a_shop()
        referrer = make_user(_next_name("referrer"))
        friend = make_user(_next_name("friend"))
        code = referrals.code_for(referrer).code

        client, token = logged_in(friend)
        created = book(client, token, profile, profile.services.first(), referral_code=code)
        complete(Booking.objects.get(reference=created.data["reference"]))

        entry = LoyaltyLedgerEntry.objects.filter(customer=referrer, reason="referral").get()
        assert entry.expires_at is not None
        assert loyalty.balance(referrer).available >= referrals.REFERRER_POINTS

    def test_the_amount_paid_out_is_recorded(self):
        """So a later change to the reward cannot rewrite history."""
        profile = a_shop()
        referrer = make_user(_next_name("referrer"))
        friend = make_user(_next_name("friend"))
        code = referrals.code_for(referrer).code

        client, token = logged_in(friend)
        created = book(client, token, profile, profile.services.first(), referral_code=code)
        complete(Booking.objects.get(reference=created.data["reference"]))

        referral = Referral.objects.get()
        assert referral.referrer_points == referrals.REFERRER_POINTS
        assert referral.referred_points == referrals.REFERRED_POINTS
        assert referral.rewarded_at is not None
