"""Abuse and no-show scoring.

The category sells this as "no-show intelligence". What it actually is, is a
little arithmetic plus a lot of judgement about what to do with it - and the
judgement is where it goes wrong.

The acceptance case is one sentence: *a customer with two no-shows in five
bookings is recommended a deposit, and the recommendation is advisory, not
enforced.* Both halves matter, and the second is the half that is easy to
break by accident.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from risk import scoring
from risk.models import CustomerRisk, RiskFlag
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

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def a_shop() -> Any:
    owner = make_provider_user(_next_name("shop"))
    return make_profile(owner, display_name="Sharp Cuts Studio")


def a_customer() -> Any:
    return make_user(_next_name("customer"))


def a_history(profile, customer, outcomes: list[str]) -> None:
    """Give a customer a record.

    ``outcomes`` are booking statuses, newest last, created far enough in the
    past that the 30-day flag sweep can see them.
    """
    for index, status in enumerate(outcomes):
        starts_at = timezone.now() - timedelta(days=30 - index)
        Booking.objects.create(
            customer=customer,
            provider=profile,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=BookingStatus(status),
            subtotal=20000,
            platform_fee=200,
            total=20200,
            deposit=10100,
            balance=10100,
            created_at=starts_at,
        )


class TestTheAcceptanceCase:
    def test_two_no_shows_in_five_is_recommended_a_deposit(self):
        profile = a_shop()
        customer = a_customer()

        a_history(
            profile,
            customer,
            [
                BookingStatus.COMPLETED,
                BookingStatus.NO_SHOW,
                BookingStatus.COMPLETED,
                BookingStatus.NO_SHOW,
                BookingStatus.COMPLETED,
            ],
        )

        result = scoring.assess(customer, profile)

        assert result.no_shows == 2
        assert result.completed == 3
        assert result.level == "medium"
        assert result.suggested_deposit_percent == 50

    def test_and_the_recommendation_is_advisory(self):
        """The price must not move.

        A score that quietly raises what somebody pays is a score that ends in
        a chargeback, with the shop none the wiser.
        """
        profile = a_shop()
        service = make_service(profile, price=20000, deposit_percent=0)
        customer = a_customer()
        a_history(
            profile,
            customer,
            [
                BookingStatus.COMPLETED,
                BookingStatus.NO_SHOW,
                BookingStatus.COMPLETED,
                BookingStatus.NO_SHOW,
            ],
        )

        client, token = logged_in(customer)
        starts_at = (timezone.localtime() + timedelta(days=5)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        response = client.post(
            f"{BOOKINGS}quote/",
            {
                "provider": profile.pk,
                "services": [service.pk],
                "starts_at": starts_at.isoformat(),
            },
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200, response.data
        assert response.data["risk"]["suggested_deposit_percent"] == 50
        # Advisory. This is the assertion that matters.
        assert response.data["risk"]["advisory"] is True
        assert response.data["deposit_percent"] == 0
        assert response.data["deposit"] == 0

    def test_and_it_is_carried_into_the_booking_too(self):
        """Same booking, same numbers: a quote that disagrees with the charge is
        the bug this feature could easily cause."""
        profile = a_shop()
        service = make_service(profile, price=20000, deposit_percent=0)
        customer = a_customer()
        a_history(
            profile,
            customer,
            [
                BookingStatus.NO_SHOW,
                BookingStatus.COMPLETED,
                BookingStatus.NO_SHOW,
                BookingStatus.COMPLETED,
            ],
        )

        client, token = logged_in(customer)
        starts_at = (timezone.localtime() + timedelta(days=5)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        booked = client.post(
            f"{BOOKINGS}new/",
            {
                "provider": profile.pk,
                "services": [service.pk],
                "starts_at": starts_at.isoformat(),
            },
            content_type="application/json",
            **auth_header(token),
        )
        assert booked.status_code == 201, booked.data
        booking = Booking.objects.get(reference=booked.data["reference"])

        # Nobody was charged a penny extra.
        assert booking.deposit == 0
        assert booking.balance == booking.total


class TestNotEnoughHistory:
    def test_one_no_show_in_one_booking_says_nothing(self):
        """A hundred per cent rate, and completely meaningless.

        A system that flags on the first one trains every provider to ignore
        the flag.
        """
        profile = a_shop()
        customer = a_customer()
        a_history(profile, customer, [BookingStatus.NO_SHOW])

        result = scoring.assess(customer, profile)

        assert result.no_show_rate == 1.0
        assert result.level is None
        assert result.suggested_deposit_percent is None

    def test_a_customer_with_no_history_is_not_a_risk(self):
        """Unknown is not the same as known-good, and unknown is not risky
        either - or every new customer gets a deposit."""
        profile = a_shop()
        customer = a_customer()

        result = scoring.assess(customer, profile)

        assert result.total == 0
        assert result.level is None
        assert result.as_payload()["suggested_deposit_percent"] is None

    def test_two_bookings_is_still_not_enough(self):
        profile = a_shop()
        customer = a_customer()
        a_history(profile, customer, [BookingStatus.NO_SHOW, BookingStatus.NO_SHOW])

        assert scoring.assess(customer, profile).level is None

    def test_a_clean_record_says_nothing(self):
        profile = a_shop()
        customer = a_customer()
        a_history(profile, customer, [BookingStatus.COMPLETED] * 4)

        result = scoring.assess(customer, profile)

        assert result.level is None
        assert result.suggested_deposit_percent is None


class TestTheArithmetic:
    def test_a_cancellation_by_the_shop_is_not_held_against_them(self):
        profile = a_shop()
        customer = a_customer()
        a_history(
            profile,
            customer,
            [
                BookingStatus.CANCELLED_BY_PROVIDER,
                BookingStatus.CANCELLED_BY_PROVIDER,
                BookingStatus.COMPLETED,
                BookingStatus.COMPLETED,
            ],
        )

        result = scoring.assess(customer, profile)

        assert result.cancelled == 2, "the record should show what happened"
        assert result.cancel_rate == 0.0, "...without blaming the customer"
        assert result.level is None

    def test_an_unpaid_booking_does_not_count(self):
        profile = a_shop()
        customer = a_customer()
        a_history(profile, customer, [BookingStatus.COMPLETED])
        Booking.objects.create(
            customer=customer,
            provider=profile,
            starts_at=timezone.now() + timedelta(days=2),
            ends_at=timezone.now() + timedelta(days=2, minutes=30),
            status=BookingStatus.PENDING_PAYMENT,
            subtotal=20000,
            platform_fee=200,
            total=20200,
            deposit=10100,
            balance=10100,
        )

        assert scoring.assess(customer, profile).total == 1

    def test_it_is_per_shop(self):
        """A bad month at one barber is not a bad month at every barber."""
        good_shop = a_shop()
        bad_shop = a_shop()
        customer = a_customer()
        a_history(bad_shop, customer, [BookingStatus.NO_SHOW] * 2)
        a_history(good_shop, customer, [BookingStatus.COMPLETED] * 4)

        assert scoring.assess(customer, bad_shop).no_shows == 2
        assert scoring.assess(customer, good_shop).level is None

    def test_a_repeat_no_show_run_is_high(self):
        profile = a_shop()
        customer = a_customer()
        a_history(
            profile,
            customer,
            [
                BookingStatus.NO_SHOW,
                BookingStatus.NO_SHOW,
                BookingStatus.NO_SHOW,
                BookingStatus.COMPLETED,
            ],
        )

        result = scoring.assess(customer, profile)

        assert result.level == "high"
        assert result.suggested_deposit_percent == 100


class TestCancellingIsNotTheSameAsNotTurningUp:
    def test_it_only_suggests_a_small_deposit(self):
        """Mass cancelling is usually a diary clash, and calling it the same as
        not turning up is how a shop stops trusting the score."""
        profile = a_shop()
        customer = a_customer()
        a_history(
            profile,
            customer,
            [
                BookingStatus.CANCELLED_BY_CUSTOMER,
                BookingStatus.CANCELLED_BY_CUSTOMER,
                BookingStatus.CANCELLED_BY_CUSTOMER,
                BookingStatus.COMPLETED,
            ],
        )

        result = scoring.assess(customer, profile)

        assert result.cancel_rate == 0.75
        assert result.level == "low"
        assert result.suggested_deposit_percent == 25

    def test_the_suggestion_never_lowers_the_shops_own_policy(self):
        profile = a_shop()
        customer = a_customer()

        assert scoring.suggested_deposit_percent(profile, customer, default=100) == 100, (
            "a low-risk customer must not get a smaller deposit than the service sets"
        )


class TestFlags:
    def test_repeat_no_shows_raise_one(self):
        profile = a_shop()
        customer = a_customer()
        a_history(
            profile,
            customer,
            [BookingStatus.NO_SHOW, BookingStatus.NO_SHOW, BookingStatus.COMPLETED],
        )

        scoring.sweep_for_flags()

        assert RiskFlag.objects.filter(
            customer=customer, kind=RiskFlag.Kind.REPEAT_NO_SHOW
        ).exists()

    def test_a_single_no_show_does_not(self):
        profile = a_shop()
        customer = a_customer()
        a_history(
            profile,
            customer,
            [BookingStatus.NO_SHOW, BookingStatus.COMPLETED, BookingStatus.COMPLETED],
        )

        scoring.sweep_for_flags()

        assert not RiskFlag.objects.filter(
            customer=customer, kind=RiskFlag.Kind.REPEAT_NO_SHOW
        ).exists()

    def test_booking_and_cancelling_repeatedly_is_flagged(self):
        profile = a_shop()
        customer = a_customer()
        a_history(profile, customer, [BookingStatus.CANCELLED_BY_CUSTOMER] * 3)

        scoring.sweep_for_flags()

        assert RiskFlag.objects.filter(
            customer=customer, kind=RiskFlag.Kind.SERIAL_CANCELLER
        ).exists()

    def test_a_busy_customer_is_not_flagged_for_it(self):
        """Booked and cancelled *and* turned up to things is just a diary."""
        profile = a_shop()
        customer = a_customer()
        a_history(
            profile,
            customer,
            [
                BookingStatus.CANCELLED_BY_CUSTOMER,
                BookingStatus.CANCELLED_BY_CUSTOMER,
                BookingStatus.CANCELLED_BY_CUSTOMER,
                BookingStatus.COMPLETED,
                BookingStatus.COMPLETED,
                BookingStatus.COMPLETED,
            ],
        )

        scoring.sweep_for_flags()

        assert not RiskFlag.objects.filter(
            customer=customer, kind=RiskFlag.Kind.SERIAL_CANCELLER
        ).exists()

    def test_a_note_trying_to_move_things_off_platform_is_flagged(self):
        profile = a_shop()
        customer = a_customer()
        starts_at = timezone.now() - timedelta(days=1)
        Booking.objects.create(
            customer=customer,
            provider=profile,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=BookingStatus.COMPLETED,
            subtotal=20000,
            platform_fee=200,
            total=20200,
            deposit=10100,
            balance=10100,
            notes="Just call me on my number, no need to book through the app",
        )

        scoring.sweep_for_flags()

        assert RiskFlag.objects.filter(
            customer=customer, kind=RiskFlag.Kind.SUSPICIOUS_NOTES
        ).exists()

    def test_an_ordinary_note_is_not(self):
        profile = a_shop()
        customer = a_customer()
        starts_at = timezone.now() - timedelta(days=1)
        Booking.objects.create(
            customer=customer,
            provider=profile,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            status=BookingStatus.COMPLETED,
            subtotal=20000,
            platform_fee=200,
            total=20200,
            deposit=10100,
            balance=10100,
            notes="Keep it short please, and not too close to the sides.",
        )

        scoring.sweep_for_flags()

        assert not RiskFlag.objects.filter(
            customer=customer, kind=RiskFlag.Kind.SUSPICIOUS_NOTES
        ).exists()

    def test_sweeping_twice_does_not_duplicate_a_flag(self):
        profile = a_shop()
        customer = a_customer()
        a_history(
            profile,
            customer,
            [BookingStatus.NO_SHOW, BookingStatus.NO_SHOW, BookingStatus.COMPLETED],
        )

        scoring.sweep_for_flags()
        scoring.sweep_for_flags()

        assert (
            RiskFlag.objects.filter(customer=customer, kind=RiskFlag.Kind.REPEAT_NO_SHOW).count()
            == 1
        )

    def test_a_cleared_flag_stops_counting(self):
        """Otherwise a bad month is a life sentence."""
        profile = a_shop()
        customer = a_customer()
        a_history(
            profile,
            customer,
            [BookingStatus.NO_SHOW, BookingStatus.NO_SHOW, BookingStatus.COMPLETED],
        )
        scoring.sweep_for_flags()

        row = RiskFlag.objects.get(customer=customer)
        scoring.clear(row, by=profile.user)

        assert RiskFlag.objects.filter(customer=customer, cleared_at__isnull=True).count() == 0
        assert scoring.assess(customer, profile).flags == ()

    def test_a_flag_appears_in_the_assessment(self):
        profile = a_shop()
        customer = a_customer()
        scoring.flag(
            customer,
            profile,
            kind=RiskFlag.Kind.REPEAT_NO_SHOW,
            severity=RiskFlag.Severity.MEDIUM,
            reason="Two no-shows",
        )

        result = scoring.assess(customer, profile)

        assert [flag_row.kind for flag_row in result.flags] == [RiskFlag.Kind.REPEAT_NO_SHOW]
        assert result.as_payload()["flags"][0]["reason"] == "Two no-shows"


class TestTheCachedProfile:
    def test_it_is_stored_and_refreshable(self):
        profile = a_shop()
        customer = a_customer()
        a_history(profile, customer, [BookingStatus.COMPLETED, BookingStatus.NO_SHOW])

        stored = scoring.refresh(customer, profile)

        assert stored.total_bookings == 2
        assert CustomerRisk.objects.filter(customer=customer, provider=profile).count() == 1

    def test_it_is_a_cache_not_the_truth(self):
        """Change the bookings, refresh, and the number follows.

        This is the property a running total does not have.
        """
        profile = a_shop()
        customer = a_customer()
        a_history(profile, customer, [BookingStatus.COMPLETED])
        scoring.refresh(customer, profile)

        a_history(profile, customer, [BookingStatus.NO_SHOW])
        scoring.refresh(customer, profile)
        stored = CustomerRisk.objects.get(customer=customer, provider=profile)

        assert stored.no_shows == 1
        assert stored.total_bookings == 2


class TestTheProviderEndpoint:
    def test_a_shop_can_look_at_one_of_their_customers(self):
        profile = a_shop()
        customer = a_customer()
        a_history(
            profile,
            customer,
            [
                BookingStatus.COMPLETED,
                BookingStatus.NO_SHOW,
                BookingStatus.COMPLETED,
                BookingStatus.NO_SHOW,
            ],
        )
        client, token = logged_in(profile.user)

        response = client.get(f"{V1}/risk/customers/{customer.pk}/", **auth_header(token))

        assert response.status_code == 200
        assert response.data["risk_level"] == "medium"
        assert response.data["advisory"] is True
        assert response.data["customer_display_name"] == customer.display_name

    def test_a_customer_is_not_a_provider(self):
        customer = a_customer()
        client, token = logged_in(customer)

        response = client.get(f"{V1}/risk/customers/{customer.pk}/", **auth_header(token))

        assert response.status_code in (403, 404)

    def test_a_flag_can_be_cleared_through_the_api(self):
        profile = a_shop()
        customer = a_customer()
        row = scoring.flag(
            customer,
            profile,
            kind=RiskFlag.Kind.REPEAT_NO_SHOW,
            severity=RiskFlag.Severity.MEDIUM,
            reason="Two no-shows",
        )
        client, token = logged_in(profile.user)

        response = client.post(f"{V1}/risk/flags/{row.pk}/clear/", {}, **auth_header(token))

        assert response.status_code == 200
        row.refresh_from_db()
        assert row.cleared_at is not None

    def test_a_shop_cannot_clear_another_shops_flag(self):
        profile = a_shop()
        other = a_shop()
        customer = a_customer()
        row = scoring.flag(
            customer,
            profile,
            kind=RiskFlag.Kind.REPEAT_NO_SHOW,
            severity=RiskFlag.Severity.MEDIUM,
            reason="Two no-shows",
        )
        client, token = logged_in(other.user)

        response = client.post(f"{V1}/risk/flags/{row.pk}/clear/", {}, **auth_header(token))

        assert response.status_code == 404
        row.refresh_from_db()
        assert row.cleared_at is None
