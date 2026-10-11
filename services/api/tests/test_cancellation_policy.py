"""The cancellation policy.

Two rules carry all the weight here, and both are about not surprising
somebody after the fact:

- The policy is **frozen on the booking**. Read live, a shop could tighten its
  window on Monday and a customer who booked on Sunday would owe money they
  never agreed to.
- The penalty is **one-directional**. A customer cancelling late forfeits a
  slice of their deposit, because the slot is nearly gone. A provider
  cancelling is always free, because the shop still has the chair and the
  customer is not at fault.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from bookings.policy import refundable_for
from core.money import compute_deposit
from payments.choices import PaymentKind
from payments.models import Payment, PaymentStatus
from tests.factories import (
    auth_header,
    logged_in,
    make_profile,
    make_service,
    make_user,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
BOOKINGS = f"{V1}/bookings/"


def cancellable(*, window_hours: int = 24, late_fee_percent: int = 50, paid=True, hours_away=48):
    """A booking with a policy, a captured deposit, and a captured balance."""
    provider = make_profile(
        cancellation_window_hours=window_hours,
        late_cancel_fee_percent=late_fee_percent,
    )
    price = 300000
    service = make_service(provider, price=price, deposit_percent=30)
    customer = make_user()

    total = price + 3000
    deposit, balance = compute_deposit(total, 30)
    late_fee, _ = compute_deposit(deposit, late_fee_percent)

    starts_at = timezone.now() + timedelta(hours=hours_away)
    booking = Booking.objects.create(
        customer=customer,
        provider=provider,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        subtotal=price,
        platform_fee=3000,
        total=total,
        deposit=deposit,
        balance=balance,
        cancellation_window_hours=window_hours,
        late_cancel_fee_percent=late_fee_percent,
        late_cancel_fee=late_fee,
        status=BookingStatus.CONFIRMED,
    )
    booking.items.create(service=service, name=service.name, unit_price=price, quantity=1)

    if paid:
        for kind, amount in ((PaymentKind.DEPOSIT, deposit), (PaymentKind.BALANCE, balance)):
            Payment.objects.create(
                booking=booking,
                kind=kind,
                razorpay_order_id=f"order_{kind}",
                amount=amount,
                status=PaymentStatus.CAPTURED,
            )
        booking.refresh_from_db()

    return booking, customer, provider


# ---------------------------------------------------------------------------
# The deadline
# ---------------------------------------------------------------------------


class TestCancellationDeadline:
    def test_is_the_start_minus_the_window(self):
        booking, *_ = cancellable(window_hours=24, hours_away=48)

        assert booking.cancellation_deadline == booking.starts_at - timedelta(hours=24)

    def test_a_cancellation_before_it_is_free(self):
        booking, *_ = cancellable(window_hours=24, hours_away=48)

        assert booking.is_late_cancellation() is False

    def test_a_cancellation_after_it_is_late(self):
        booking, *_ = cancellable(window_hours=24, hours_away=2)

        assert booking.is_late_cancellation() is True

    def test_a_zero_hour_window_means_any_cancellation_is_late(self):
        booking, *_ = cancellable(window_hours=0, hours_away=48)

        assert booking.is_late_cancellation() is True

    def test_the_exact_moment_counts_as_late(self):
        booking, *_ = cancellable(window_hours=24, hours_away=24)

        # On the deadline itself the customer is late. Being generous by one
        # instant is a hole in a policy that exists to be enforced.
        assert booking.is_late_cancellation() is True


# ---------------------------------------------------------------------------
# The policy is frozen
# ---------------------------------------------------------------------------


class TestPolicyIsFrozen:
    def test_the_window_is_copied_onto_the_booking(self):
        booking, *_ = cancellable(window_hours=6)

        assert booking.cancellation_window_hours == 6

    def test_tightening_the_shop_policy_does_not_reach_old_bookings(self):
        # Booked 100 hours ahead, so the customer has more than the agreed 48
        # hours' notice and cancelling is free.
        booking, *_ = cancellable(window_hours=48, hours_away=100)
        assert booking.is_late_cancellation() is False

        # The shop tightens to an hour, which would make this booking late.
        booking.provider.cancellation_window_hours = 1
        booking.provider.save(update_fields=["cancellation_window_hours"])
        booking.refresh_from_db()

        # The customer agreed to 48 hours. The shop tightening it on Monday
        # cannot reach back into a booking made last week.
        assert booking.cancellation_window_hours == 48
        assert booking.is_late_cancellation() is False

    def test_raising_the_fee_does_not_reach_old_bookings(self):
        booking, _customer, provider = cancellable(late_fee_percent=25, hours_away=2)
        promised = booking.late_cancel_fee

        provider.late_cancel_fee_percent = 100
        provider.save(update_fields=["late_cancel_fee_percent"])
        booking.refresh_from_db()

        assert booking.late_cancel_fee == promised

    def test_the_fee_is_computed_from_the_deposit_not_the_total(self):
        booking, *_ = cancellable(late_fee_percent=50)

        assert booking.late_cancel_fee == booking.deposit // 2


# ---------------------------------------------------------------------------
# Cancelling
# ---------------------------------------------------------------------------


class TestCancelling:
    def test_a_prompt_cancellation_refunds_everything(self):
        booking, customer, _ = cancellable(hours_away=48)
        client, token = logged_in(customer)

        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Something came up"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        outcome = response.data["cancellation"]
        assert outcome["is_late"] is False
        assert outcome["deposit_forfeited"] == 0
        assert outcome["deposit_refundable"] == booking.deposit

    def test_a_late_cancellation_forfeits_the_agreed_slice(self):
        booking, customer, _ = cancellable(hours_away=2)
        client, token = logged_in(customer)

        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Late change"},
            content_type="application/json",
            **auth_header(token),
        )

        outcome = response.data["cancellation"]
        assert outcome["is_late"] is True
        assert outcome["deposit_forfeited"] == booking.late_cancel_fee
        assert outcome["deposit_refundable"] == booking.deposit - booking.late_cancel_fee

    def test_the_forfeiture_never_exceeds_the_deposit(self):
        booking, customer, _ = cancellable(hours_away=2, late_fee_percent=100)
        client, token = logged_in(customer)

        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Late"},
            content_type="application/json",
            **auth_header(token),
        )

        outcome = response.data["cancellation"]
        assert outcome["deposit_forfeited"] == booking.deposit
        assert outcome["deposit_refundable"] == 0

    def test_a_late_cancellation_still_succeeds(self):
        # The refusal case is a booking that cannot be cancelled at all. A late
        # cancellation is allowed and costs money — refusing it would just
        # leave the shop with a slot nobody is coming to.
        booking, customer, _ = cancellable(hours_away=2)
        client, token = logged_in(customer)

        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Late"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        booking.refresh_from_db()
        assert booking.status == BookingStatus.CANCELLED_BY_CUSTOMER

    def test_a_provider_cancelling_is_never_penalised(self):
        # The shop has the chair. Charging the customer for the shop's own
        # change of plan would be indefensible.
        booking, _customer, provider = cancellable(hours_away=2)
        client, token = logged_in(provider.user)

        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Ill"},
            content_type="application/json",
            **auth_header(token),
        )

        outcome = response.data["cancellation"]
        assert outcome["by_provider"] is True
        assert outcome["is_late"] is False
        assert outcome["deposit_forfeited"] == 0
        assert outcome["deposit_refundable"] == booking.deposit

    def test_a_provider_cancelling_an_appointment_that_has_not_started_still_refunds(
        self,
    ):
        booking, _customer, provider = cancellable(hours_away=200)
        client, token = logged_in(provider.user)

        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Shut today"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.data["cancellation"]["deposit_refundable"] == booking.deposit

    def test_the_response_explains_itself_in_words(self):
        booking, customer, _ = cancellable(hours_away=2)
        client, token = logged_in(customer)

        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Late"},
            content_type="application/json",
            **auth_header(token),
        )

        # Somebody who loses part of a deposit deserves to be told here, not by
        # noticing on their statement a week later.
        assert "window" in response.data["cancellation"]["message"]
        assert "₹" in response.data["cancellation"]["message"]

    def test_an_unpaid_booking_forfeits_nothing(self):
        booking, customer, _ = cancellable(hours_away=2, paid=False)
        client, token = logged_in(customer)

        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Late"},
            content_type="application/json",
            **auth_header(token),
        )

        # Nothing was taken, so nothing can be kept.
        assert response.data["cancellation"]["deposit_forfeited"] == 0

    def test_a_zero_fee_policy_late_cancellation_returns_everything(self):
        booking, customer, _ = cancellable(hours_away=2, late_fee_percent=0)
        client, token = logged_in(customer)

        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Late"},
            content_type="application/json",
            **auth_header(token),
        )

        outcome = response.data["cancellation"]
        assert outcome["is_late"] is True
        assert outcome["deposit_forfeited"] == 0

    def test_a_cancelled_booking_cannot_be_cancelled_again(self):
        booking, customer, _ = cancellable()
        client, token = logged_in(customer)
        client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Once"},
            content_type="application/json",
            **auth_header(token),
        )

        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Twice"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_a_stranger_cannot_cancel_someone_elses_booking(self):
        booking, _customer, _provider = cancellable()
        client, token = logged_in(make_user("nosy"))

        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Not mine"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 404
        booking.refresh_from_db()
        assert booking.status == BookingStatus.CONFIRMED


class TestRefundable:
    def test_matches_what_the_cancellation_promised(self):
        booking, customer, _ = cancellable(hours_away=2)
        client, token = logged_in(customer)
        response = client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Late"},
            content_type="application/json",
            **auth_header(token),
        )
        booking.refresh_from_db()

        promised = response.data["cancellation"]["deposit_refundable"]

        # The number promised at cancellation time must be the number actually
        # refunded, or the promise is a decoration.
        assert promised == refundable_for(booking, forfeited=booking.late_cancel_fee)

    def test_is_never_negative(self):
        booking, customer, _ = cancellable(hours_away=2, late_fee_percent=100)
        client, token = logged_in(customer)
        client.post(
            f"{BOOKINGS}{booking.reference}/cancel/",
            {"reason": "Late"},
            content_type="application/json",
            **auth_header(token),
        )
        booking.refresh_from_db()

        assert refundable_for(booking, forfeited=booking.late_cancel_fee) == 0
