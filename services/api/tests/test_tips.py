"""Tips.

A tip is not part of what the appointment cost. Everything here follows from
that one fact, and it is the thing that goes wrong when tips get bolted onto
booking totals: the deposit split moves, anything measured off "total" moves,
and the platform takes a percentage of somebody's thank-you.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from payments.ledger import balance_for
from payments.models import Payment, PaymentStatus, Tip
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
PAYMENTS = f"{V1}/payments/"

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def a_completed_booking(
    staff: Staff | None = None, profile: Any = None
) -> tuple[Any, Any, Booking]:
    if profile is None:
        owner = make_provider_user(_next_name("shop"))
        profile = make_profile(owner, display_name="Sharp Cuts Studio")
        make_service(profile, price=20000)
    customer = make_user(_next_name("customer"))
    starts_at = timezone.localtime() + timedelta(days=1)

    booking = Booking.objects.create(
        customer=customer,
        provider=profile,
        staff=staff,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        status=BookingStatus.COMPLETED,
        subtotal=20000,
        platform_fee=200,
        total=20200,
    )
    return customer, profile, booking


def a_tip_payment(booking: Booking, amount: int = 5000, staff=None) -> Payment:
    return Payment.objects.create(
        booking=booking,
        kind="tip",
        amount=amount,
        currency="INR",
        status=PaymentStatus.CREATED,
        staff=staff,
        razorpay_order_id=f"order_{_next_name('o')}",
    )


class TestWhatATipIsNot:
    def test_it_does_not_change_the_booking_total(self):
        _customer, _profile, booking = a_completed_booking()
        before = (booking.subtotal, booking.platform_fee, booking.total, booking.deposit)

        tip = a_tip_payment(booking, amount=5000)
        tip.status = PaymentStatus.CAPTURED
        tip.captured_at = timezone.now()
        tip.save()

        booking.refresh_from_db()
        assert (booking.subtotal, booking.platform_fee, booking.total, booking.deposit) == before

    def test_it_does_not_move_the_booking_status(self):
        """A tip is not a new payment for the appointment."""
        _customer, _profile, booking = a_completed_booking()
        payment = a_tip_payment(booking)

        from payments.views import capture

        capture(payment, "pay_x", "")

        booking.refresh_from_db()
        assert booking.status == BookingStatus.COMPLETED

    def test_it_does_not_move_the_deposit_split(self):
        _customer, _profile, booking = a_completed_booking()
        before = (booking.deposit, booking.balance)

        a_tip_payment(booking, amount=99999).status = PaymentStatus.CAPTURED

        booking.refresh_from_db()
        assert (booking.deposit, booking.balance) == before


class TestPaying:
    def test_a_tip_needs_the_appointment_to_have_happened(self):
        _customer, _profile, booking = a_completed_booking()
        Booking.objects.filter(pk=booking.pk).update(status=BookingStatus.CONFIRMED)
        client, token = logged_in(booking.customer)

        response = client.post(
            f"{PAYMENTS}bookings/{booking.reference}/tip/",
            {"amount": 5000},
            **auth_header(token),
        )
        assert response.status_code >= 400
        assert "happened" in str(response.data).lower()

    def test_nobody_can_tip_someone_elses_appointment(self):
        _customer, _profile, booking = a_completed_booking()
        stranger = make_user(_next_name("stranger"))
        client, token = logged_in(stranger)

        response = client.post(
            f"{PAYMENTS}bookings/{booking.reference}/tip/",
            {"amount": 5000},
            **auth_header(token),
        )
        assert response.status_code == 404

    def test_a_zero_tip_is_refused(self):
        _customer, _profile, booking = a_completed_booking()
        client, token = logged_in(booking.customer)

        response = client.post(
            f"{PAYMENTS}bookings/{booking.reference}/tip/",
            {"amount": 0},
            **auth_header(token),
        )
        assert response.status_code == 400


class TestRecording:
    def test_it_is_recorded_against_the_barber(self):
        owner = make_provider_user(_next_name("shop2"))
        profile = make_profile(owner)
        ravi = Staff.objects.create(provider=profile, name="Ravi")
        _customer, _provider, booking = a_completed_booking(staff=ravi)

        payment = a_tip_payment(booking, amount=5000, staff=ravi)
        from payments.views import capture

        capture(payment, "pay_x", "")

        tip = Tip.objects.get()
        assert tip.amount == 5000
        assert tip.staff_id == ravi.pk
        assert tip.booking_id == booking.pk

    def test_a_tip_for_the_shop_has_no_barber(self):
        _customer, _provider, booking = a_completed_booking()
        payment = a_tip_payment(booking, amount=5000)

        from payments.views import capture

        capture(payment, "pay_x", "")

        assert Tip.objects.get().staff_id is None

    def test_it_is_paid_once(self):
        """A webhook retry must not produce a second tip or a second credit."""
        _customer, _profile, booking = a_completed_booking()
        payment = a_tip_payment(booking, amount=5000)

        from payments.views import capture

        capture(payment, "pay_x", "")
        capture(payment, "pay_x", "")

        assert Tip.objects.count() == 1

    def test_a_booking_can_only_be_tipped_once(self):
        """An existing constraint, and it is the right one.

        `payments_one_captured_charge_per_kind` already stops a second captured
        charge of the same kind on one booking. That protects against a
        retried flow charging twice, and a second tip is better made on the next
        appointment than by loosening a constraint every other payment relies
        on.
        """
        from django.db.utils import IntegrityError

        _customer, _profile, booking = a_completed_booking()
        first = a_tip_payment(booking, amount=1000)
        first.status = PaymentStatus.CAPTURED
        first.save(update_fields=["status"])

        second = a_tip_payment(booking, amount=1000)
        second.status = PaymentStatus.CAPTURED
        with pytest.raises(IntegrityError):
            second.save(update_fields=["status"])


class TestTheProviderKeepsAllOfIt:
    def test_the_ledger_credits_the_full_tip(self):
        _customer, profile, booking = a_completed_booking()
        payment = a_tip_payment(booking, amount=5000)

        from payments.views import capture

        capture(payment, "pay_x", "")

        assert balance_for(profile).total == 5000

    def test_no_platform_fee_is_taken(self):
        """A fee on somebody's thank-you is not a fee, it is a grudge."""
        _customer, profile, booking = a_completed_booking()
        payment = a_tip_payment(booking, amount=5000)

        from payments.views import capture

        capture(payment, "pay_x", "")

        from payments.ledger import EntryKind
        from payments.models import LedgerEntry

        kinds = list(LedgerEntry.objects.filter(provider=profile).values_list("kind", flat=True))
        assert kinds == [EntryKind.TIP]
        assert EntryKind.PLATFORM_FEE not in kinds

    def test_a_tip_of_1000_pays_the_provider_1000(self):
        """Not 990. This is the assertion that says so out loud."""
        _customer, profile, booking = a_completed_booking()
        payment = a_tip_payment(booking, amount=1000)

        from payments.views import capture

        capture(payment, "pay_x", "")

        assert balance_for(profile).total == 1000


class TestWhatTheProviderSees:
    def test_tips_are_grouped_by_barber(self):
        owner = make_provider_user(_next_name("shop3"))
        profile = make_profile(owner)
        ravi = Staff.objects.create(provider=profile, name="Ravi")
        priya = Staff.objects.create(provider=profile, name="Priya")

        from payments.views import capture

        for staff, amount in ((ravi, 5000), (ravi, 2000), (priya, 3000)):
            _customer, _provider, booking = a_completed_booking(staff=staff, profile=profile)
            payment = a_tip_payment(booking, amount=amount, staff=staff)
            capture(payment, "pay_x", "")

        owner_client, token = logged_in(owner)
        response = owner_client.get(f"{PAYMENTS}me/tips/", **auth_header(token))

        assert response.status_code == 200
        rows = {row["who"]: row for row in response.data["by_staff"]}
        assert rows["Ravi"]["total"] == 7000
        assert rows["Ravi"]["count"] == 2
        assert rows["Priya"]["total"] == 3000

    def test_it_says_no_fee_was_taken(self):
        owner = make_provider_user(_next_name("shop4"))
        make_profile(owner)
        client, token = logged_in(owner)

        response = client.get(f"{PAYMENTS}me/tips/", **auth_header(token))

        assert response.data["platform_fee_taken"] == 0

    def test_it_needs_a_provider_account(self):
        customer = make_user(_next_name("c"))
        client, token = logged_in(customer)

        response = client.get(f"{PAYMENTS}me/tips/", **auth_header(token))
        assert response.status_code in (403, 404)


class TestAHalfFinishedTip:
    """A tip is two writes: the payment is captured, and the money is attached
    to a person and credited.

    The worry is the gap between them. `capture()` saves the payment as
    CAPTURED and then records the tip; if the second half fails after the first
    has been saved, a retry sees a captured payment, returns early, and the
    barber is never paid for the tip they were given. The provider's balance
    stays wrong with no way to correct it from the outside.

    It does not happen, because `capture()` is one transaction - and the only
    way to know that is to make the second half fail on purpose.
    """

    def test_a_failure_partway_through_leaves_nothing_captured(self, monkeypatch):
        import payments.views as views

        _customer, profile, booking = a_completed_booking()
        payment = a_tip_payment(booking, amount=5000)

        def explode(*args, **kwargs):
            raise RuntimeError("the ledger is down")

        monkeypatch.setattr(views, "_record_tip", explode)

        with pytest.raises(RuntimeError):
            views.capture(payment, "pay_x", "")

        payment.refresh_from_db()
        assert payment.status != PaymentStatus.CAPTURED, (
            "the payment stayed captured with no tip recorded against it"
        )
        assert not Tip.objects.exists()
        assert balance_for(profile).total == 0

    def test_and_the_retry_afterwards_still_works(self, monkeypatch):
        """The point of rolling back: the client's next attempt can succeed."""
        import payments.views as views

        _customer, profile, booking = a_completed_booking()
        payment = a_tip_payment(booking, amount=5000)

        def explode(*args, **kwargs):
            raise RuntimeError("the ledger is down")

        monkeypatch.setattr(views, "_record_tip", explode)
        with pytest.raises(RuntimeError):
            views.capture(payment, "pay_x", "")

        monkeypatch.undo()
        views.capture(payment, "pay_x", "")

        payment.refresh_from_db()
        assert payment.status == PaymentStatus.CAPTURED
        assert Tip.objects.count() == 1
        assert balance_for(profile).total == 5000
