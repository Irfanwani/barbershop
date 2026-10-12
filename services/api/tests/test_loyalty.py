"""Points.

Points are a promise with a cost attached. The awkward parts are all in the
edges: a balance that can go negative, a redemption that gives an appointment
away, and points that never die.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from promotions import loyalty
from promotions.models import LoyaltyLedgerEntry, LoyaltyPolicy
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
POINTS = f"{V1}/promotions/points/"

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def a_customer():
    user = make_user(_next_name("customer"))
    make_profile(user)
    return user


def a_shop(points: int = 100, *, validity_days: int = 365, max_percent: int = 20):
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner)
    LoyaltyPolicy.objects.create(
        provider=profile,
        points_per_booking=points,
        validity_days=validity_days,
        max_redemption_percent=max_percent,
    )
    return profile


def a_booking(profile, customer, *, total: int = 10000):
    # One menu item per shop; several bookings at one shop must not collide.
    profile.services.filter(is_active=True).first() or make_service(profile, price=total)
    starts_at = timezone.localtime() + timedelta(days=2)
    return Booking.objects.create(
        customer=customer,
        provider=profile,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        status=BookingStatus.COMPLETED,
        subtotal=total,
        platform_fee=0,
        total=total,
    )


class TestEarning:
    def test_completing_a_booking_credits_points(self):
        customer, profile = a_customer(), a_shop(100)
        booking = a_booking(profile, customer)

        entry = loyalty.credit(booking)

        assert entry.points == 100
        assert loyalty.balance(customer).available == 100

    def test_a_shop_that_awards_nothing_credits_nothing(self):
        customer, profile = a_customer(), a_shop(0)
        assert loyalty.credit(a_booking(profile, customer)) is None
        assert loyalty.balance(customer).available == 0

    def test_a_shop_with_no_policy_at_all(self):
        customer = a_customer()
        profile = make_profile(make_provider_user(_next_name("bare")))
        assert loyalty.credit(a_booking(profile, customer)) is None

    def test_points_are_awarded_on_completion_not_at_booking(self):
        """Otherwise a cancelled appointment earns points."""
        customer, profile = a_customer(), a_shop(100)
        booking = a_booking(profile, customer)
        booking.status = BookingStatus.CONFIRMED
        booking.save(update_fields=["status"])

        assert loyalty.balance(customer).available == 0


class TestTheBalance:
    def test_it_is_a_sum_over_the_ledger(self):
        customer, profile = a_customer(), a_shop(100)
        for _ in range(3):
            loyalty.credit(a_booking(profile, customer))

        assert loyalty.balance(customer).available == 300
        assert LoyaltyLedgerEntry.objects.filter(customer=customer).count() == 3

    def test_spending_reduces_it(self):
        customer, profile = a_customer(), a_shop(100)
        first = a_booking(profile, customer)
        second = a_booking(profile, customer)
        loyalty.credit(first)
        loyalty.credit(second)

        off = loyalty.redeem(customer, first, 100)

        assert off == 100
        assert loyalty.balance(customer).available == 100

    def test_it_is_never_negative(self):
        customer, profile = a_customer(), a_shop(100)
        booking = a_booking(profile, customer)
        loyalty.credit(booking)

        loyalty.redeem(customer, booking, 500)

        assert loyalty.balance(customer).available == 0

    def test_it_survives_the_shop_leaving_the_marketplace(self):
        """Points were earned by the customer, not by the platform."""
        customer, profile = a_customer(), a_shop(100)
        loyalty.credit(a_booking(profile, customer))

        profile.delete()

        assert loyalty.balance(customer).available == 100
        assert LoyaltyLedgerEntry.objects.filter(customer=customer).exists()

    def test_the_history_explains_the_balance(self):
        customer, profile = a_customer(), a_shop(100)
        booking = a_booking(profile, customer)
        loyalty.credit(booking)
        loyalty.redeem(customer, booking, 60)

        assert loyalty.balance(customer).available == 40
        assert [e.reason for e in LoyaltyLedgerEntry.objects.filter(customer=customer)] == [
            "earned",
            "spent",
        ]

    def test_the_same_booking_cannot_be_awarded_twice(self):
        """A database constraint, so it cannot be reintroduced by a new caller."""
        from django.db.utils import IntegrityError

        customer, profile = a_customer(), a_shop(100)
        booking = a_booking(profile, customer)
        loyalty.credit(booking)

        with pytest.raises(IntegrityError):
            loyalty.credit(booking)


class TestExpiry:
    def test_expired_points_stop_counting(self):
        customer, profile = a_customer(), a_shop(100, validity_days=1)
        loyalty.credit(a_booking(profile, customer))
        assert loyalty.balance(customer).available == 100

        LoyaltyLedgerEntry.objects.filter(customer=customer).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )

        assert loyalty.balance(customer).available == 0

    def test_no_job_has_to_rewrite_history(self):
        """Expiry is a consequence of the date, not an event to record."""
        customer, profile = a_customer(), a_shop(100, validity_days=1)
        entry = loyalty.credit(a_booking(profile, customer))
        LoyaltyLedgerEntry.objects.filter(pk=entry.pk).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )

        loyalty.balance(customer)

        entry.refresh_from_db()
        assert entry.points == 100
        assert entry.reason == "earned"

    def test_points_about_to_lapse_are_reported_separately(self):
        customer, profile = a_customer(), a_shop(100, validity_days=10)
        loyalty.credit(a_booking(profile, customer))

        assert loyalty.balance(customer).expiring_soon == 100

    def test_points_that_expire_later_are_not(self):
        customer, profile = a_customer(), a_shop(100, validity_days=300)
        loyalty.credit(a_booking(profile, customer))

        assert loyalty.balance(customer).expiring_soon == 0


class TestRedemption:
    def test_points_are_capped_at_a_share_of_the_booking(self):
        customer, profile = a_customer(), a_shop(500, max_percent=20)
        booking = a_booking(profile, customer, total=10000)
        for _ in range(5):
            loyalty.credit(a_booking(profile, customer, total=10000))

        # The cap limits how many points may be used; it does not inflate what
        # fewer points are worth.
        assert loyalty.points_spendable(customer, booking) == 2000
        assert loyalty.redeem(customer, booking, 500) == 500
        assert loyalty.redeem(customer, booking, 5000) == 2000

    def test_a_redemption_cannot_make_a_total_negative(self):
        customer, profile = a_customer(), a_shop(100000, max_percent=100)
        booking = a_booking(profile, customer, total=5000)
        loyalty.credit(booking)

        off = loyalty.redeem(customer, booking, 100000)

        assert off <= booking.total
        assert booking.total - off >= 0

    def test_spending_nothing_is_free_and_writes_nothing(self):
        customer, profile = a_customer(), a_shop(100)
        booking = a_booking(profile, customer)

        assert loyalty.redeem(customer, booking, 0) == 0
        assert not LoyaltyLedgerEntry.objects.exists()

    def test_a_shop_without_points_cannot_be_redeemed_at(self):
        customer = a_customer()
        profile = make_profile(make_provider_user(_next_name("bare")))
        booking = a_booking(profile, customer)

        assert loyalty.points_spendable(customer, booking) == 0


class TestTheEndpoints:
    def test_the_balance_is_readable(self):
        customer, profile = a_customer(), a_shop(100)
        loyalty.credit(a_booking(profile, customer))
        client, token = logged_in(customer)

        response = client.get(POINTS, **auth_header(token))

        assert response.status_code == 200
        assert response.json()["available"] == 100
        assert response.json()["worth_minor"] == 100

    def test_the_history_reads_in_words(self):
        customer, profile = a_customer(), a_shop(100)
        loyalty.credit(a_booking(profile, customer))
        client, token = logged_in(customer)

        response = client.get(f"{POINTS}history/", **auth_header(token))

        entry = response.json()["entries"][0]
        assert entry["reason"] == "earned"
        assert entry["shop"] == profile.display_name

    def test_the_usable_amount_is_capped_before_it_is_shown(self):
        """The number on the screen is the number that will be honoured."""
        customer, profile = a_customer(), a_shop(500, max_percent=20)
        booking = a_booking(profile, customer, total=10000)
        for _ in range(5):
            loyalty.credit(a_booking(profile, customer, total=10000))
        client, token = logged_in(customer)

        response = client.get(
            f"{V1}/promotions/bookings/{booking.reference}/points/", **auth_header(token)
        )

        body = response.json()
        assert body["usable_on_this_booking"] == 2000
        assert body["worth_minor"] == 2000
        assert body["worth_minor"] < body["total_minor"]

    def test_it_needs_a_signed_in_customer(self):
        from django.test import Client

        assert Client().get(POINTS).status_code in (401, 403)

    def test_a_provider_can_set_their_own_policy(self):
        owner = make_provider_user(_next_name("owner"))
        make_profile(owner)
        client, token = logged_in(owner)

        response = client.put(
            f"{POINTS}settings/",
            '{"points_per_booking": 50, "max_redemption_percent": 10}',
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200, response.data
        assert response.json()["enabled"] is True
        assert response.json()["points_per_booking"] == 50
