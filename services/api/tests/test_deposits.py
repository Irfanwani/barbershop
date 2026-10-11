"""Deposits.

A deposit is not payment. That is the whole idea, and it is the easiest thing in
this feature to get wrong: read a captured deposit as "the booking is paid" and
a shop ends up holding ₹900 against a ₹3,000 colouring job with nothing
securing the rest.

The tests are weighted towards that mistake and towards the arithmetic, because
deposit + balance not equalling total is the kind of thing a customer notices
at the till.
"""

from __future__ import annotations

import pytest

from bookings.models import Booking, BookingStatus
from core.money import compute_deposit, quote
from payments.choices import PaymentKind
from payments.due import amount_due, default_kind, requested_kind
from payments.models import Payment, PaymentStatus
from tests.factories import (
    auth_header,
    logged_in,
    make_profile,
    make_service,
    make_user,
    next_slot,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
BOOKINGS = f"{V1}/bookings/"
PAYMENTS = f"{V1}/payments/"


def booking_with_deposit(percent: int = 30, price: int = 300000):
    """A booking for a service that demands a deposit up front."""
    provider = make_profile()
    service = make_service(provider, name="Colour service", price=price, deposit_percent=percent)
    customer = make_user()
    booking = Booking.objects.create(
        customer=customer,
        provider=provider,
        starts_at=next_slot(hour=14),
        ends_at=next_slot(hour=17),
        subtotal=price,
        platform_fee=compute_deposit(price, 1)[0] // 100 or 1,
        total=price + 3000,
        deposit=compute_deposit(price + 3000, percent)[0],
        balance=compute_deposit(price + 3000, percent)[1],
        status=BookingStatus.PENDING_PAYMENT,
    )
    booking.items.create(service=service, name=service.name, unit_price=price, quantity=1)
    return booking, customer, provider


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------


class TestComputeDeposit:
    def test_a_thirty_percent_deposit_on_a_realistic_price(self):
        # ₹3,000 total: ₹900 now, ₹2,100 on arrival.
        assert compute_deposit(300000, 30) == (90000, 210000)

    def test_no_deposit_means_pay_it_all_now(self):
        assert compute_deposit(300000, 0) == (0, 300000)

    def test_a_full_deposit_leaves_nothing_due(self):
        assert compute_deposit(300000, 100) == (300000, 0)

    def test_deposit_plus_balance_is_always_exactly_the_total(self):
        # The property that matters: a receipt that does not add up to the
        # quote is a complaint at the counter.
        for total in (1, 99, 100, 101, 999, 10000, 123457):
            for percent in range(0, 101):
                deposit, balance = compute_deposit(total, percent)
                assert deposit + balance == total, (total, percent)

    def test_rounds_half_up_like_every_other_fee(self):
        assert compute_deposit(101, 50)[0] == 51
        assert compute_deposit(105, 50)[0] == 53

    def test_a_deposit_can_never_exceed_the_total(self):
        deposit, balance = compute_deposit(100, 150)

        assert deposit == 100
        assert balance == 0


class TestQuoteCarriesDeposit:
    def test_the_quote_shows_the_deposit_before_checkout(self):
        quoted = quote([(1, "Colour", 300000, 120)], fee_percent=1, deposit_percent=30)

        assert quoted.total == 303000
        assert quoted.deposit == 90900
        assert quoted.balance == 212100

    def test_the_deposit_is_taken_from_the_total_not_the_subtotal(self):
        # Taking it from the subtotal would quietly move money out of the
        # platform's own fee.
        quoted = quote([(1, "Colour", 300000, 120)], fee_percent=1, deposit_percent=30)

        assert quoted.deposit == quoted.total * 30 // 100


# ---------------------------------------------------------------------------
# A deposit is not payment
# ---------------------------------------------------------------------------


class TestDepositIsNotPayment:
    def test_a_booking_with_a_deposit_is_not_paid(self):
        booking, *_ = booking_with_deposit()

        assert booking.deposit > 0
        assert booking.balance > 0
        assert booking.is_paid is False

    def test_a_captured_deposit_does_not_make_the_booking_paid(self):
        booking, *_ = booking_with_deposit()
        Payment.objects.create(
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            razorpay_order_id="order_dep",
            amount=booking.deposit,
            status=PaymentStatus.CAPTURED,
        )
        booking.refresh_from_db()

        # The mistake this whole feature exists to prevent.
        assert booking.amount_paid == booking.deposit
        assert booking.is_paid is False
        assert booking.requires_deposit is False

    def test_a_booking_with_no_deposit_policy_is_paid_once_captured(self):
        booking, _customer, _provider = booking_with_deposit()
        booking.deposit = 0
        booking.balance = 0
        booking.save()
        Payment.objects.create(
            booking=booking,
            kind=PaymentKind.FULL,
            razorpay_order_id="order_full",
            amount=booking.total,
            status=PaymentStatus.CAPTURED,
        )
        booking.refresh_from_db()

        assert booking.is_paid is True

    def test_amount_paid_adds_up_the_deposit_and_the_balance(self):
        booking, *_ = booking_with_deposit()
        for kind, amount in (
            (PaymentKind.DEPOSIT, booking.deposit),
            (PaymentKind.BALANCE, booking.balance),
        ):
            Payment.objects.create(
                booking=booking,
                kind=kind,
                razorpay_order_id=f"order_{kind}",
                amount=amount,
                status=PaymentStatus.CAPTURED,
            )
        booking.refresh_from_db()

        assert booking.amount_paid == booking.total
        assert booking.is_paid is True


class TestAmountDue:
    def test_nothing_is_due_once_the_deposit_is_paid(self):
        booking, *_ = booking_with_deposit()

        assert amount_due(booking, PaymentKind.DEPOSIT) == booking.deposit
        assert amount_due(booking, PaymentKind.BALANCE) == booking.balance

    def test_the_balance_shrinks_by_a_captured_deposit(self):
        booking, *_ = booking_with_deposit()
        Payment.objects.create(
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            razorpay_order_id="order_dep",
            amount=booking.deposit,
            status=PaymentStatus.CAPTURED,
        )
        booking.refresh_from_db()

        assert amount_due(booking, PaymentKind.DEPOSIT) == 0
        assert amount_due(booking, PaymentKind.BALANCE) == booking.balance

    def test_a_deposit_is_only_owed_once(self):
        booking, *_ = booking_with_deposit()
        Payment.objects.create(
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            razorpay_order_id="order_dep",
            amount=booking.deposit,
            status=PaymentStatus.CAPTURED,
        )
        booking.refresh_from_db()

        assert amount_due(booking, PaymentKind.DEPOSIT) == 0

    def test_nothing_can_be_overpaid(self):
        booking, *_ = booking_with_deposit()
        booking.total = 100

        assert amount_due(booking, PaymentKind.BALANCE) <= 100


class TestDefaultKind:
    def test_a_booking_needing_a_deposit_owes_the_deposit_first(self):
        booking, *_ = booking_with_deposit()

        assert default_kind(booking) == PaymentKind.DEPOSIT

    def test_once_paid_the_balance_is_next(self):
        booking, *_ = booking_with_deposit()
        Payment.objects.create(
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            razorpay_order_id="order_dep",
            amount=booking.deposit,
            status=PaymentStatus.CAPTURED,
        )
        booking.refresh_from_db()

        assert default_kind(booking) == PaymentKind.BALANCE

    def test_a_booking_with_no_deposit_policy_is_paid_in_full(self):
        booking, _customer, _provider = booking_with_deposit()
        booking.deposit = 0
        booking.balance = 0
        booking.save()

        assert default_kind(booking) == PaymentKind.FULL


class TestRequestedKind:
    def _request(self, **attrs):
        class R:
            query_params = {}
            data = attrs

        return R()

    def test_an_asked_for_kind_is_honoured(self):
        assert requested_kind(self._request(kind="balance")) == PaymentKind.BALANCE

    def test_an_invented_kind_is_ignored(self):
        # This decides how much money to ask for, so a caller must not be able
        # to name an arbitrary kind and get an arbitrary amount.
        assert requested_kind(self._request(kind="free")) == ""

    def test_nothing_asked_for_falls_back(self):
        assert requested_kind(self._request()) == ""


# ---------------------------------------------------------------------------
# Booking creation
# ---------------------------------------------------------------------------


class TestBookingCreation:
    def _book(self, client, token, provider, services):
        return client.post(
            f"{BOOKINGS}new/",
            {
                "provider": provider.id,
                "services": [service.id for service in services],
                "starts_at": next_slot(hour=12).isoformat(),
            },
            content_type="application/json",
            **auth_header(token),
        )

    def test_a_service_with_a_deposit_stores_the_split(self, client):
        provider = make_profile()
        service = make_service(provider, price=300000, deposit_percent=30)
        client_, token = logged_in(make_user())

        body = self._book(client_, token, provider, [service]).json()

        assert body["deposit"] == 90900
        assert body["balance"] == 212100
        assert body["deposit"] + body["balance"] == body["total"]

    def test_a_service_with_no_deposit_stores_none(self, client):
        provider = make_profile()
        service = make_service(provider, price=20000, deposit_percent=0)
        client_, token = logged_in(make_user())

        body = self._book(client_, token, provider, [service]).json()

        assert body["deposit"] == 0
        assert body["balance"] == body["total"]

    def test_a_basket_takes_the_strictest_deposit(self, client):
        # Booking a colour service and a trim: the colour service's policy wins.
        # Averaging would under-charge on the thing that costs the chair time.
        provider = make_profile()
        colour = make_service(provider, name="Colour", price=300000, deposit_percent=40)
        trim = make_service(provider, name="Trim", price=20000, deposit_percent=0)
        client_, token = logged_in(make_user())

        body = self._book(client_, token, provider, [colour, trim]).json()

        assert body["deposit"] == body["total"] * 40 // 100

    def test_the_deposit_is_frozen_on_the_booking(self, client):
        provider = make_profile()
        service = make_service(provider, price=300000, deposit_percent=30)
        client_, token = logged_in(make_user())

        body = self._book(client_, token, provider, [service]).json()
        service.deposit_percent = 100
        service.save()

        booking = Booking.objects.get(reference=body["reference"])
        assert booking.deposit == 90900, "a policy change moved an existing booking"


# ---------------------------------------------------------------------------
# The quote the customer sees
# ---------------------------------------------------------------------------


class TestQuoteShowsDeposit:
    def test_the_quote_carries_the_deposit(self, client):
        provider = make_profile()
        service = make_service(provider, price=300000, deposit_percent=30)
        client_, token = logged_in(make_user())

        body = client_.post(
            f"{BOOKINGS}quote/",
            {
                "provider": provider.id,
                "services": [service.id],
                "starts_at": next_slot(hour=12).isoformat(),
            },
            content_type="application/json",
            **auth_header(token),
        ).json()

        # Shown before checkout. A deposit discovered at the payment screen is
        # a complaint.
        assert body["deposit"] == 90900
        assert body["deposit_display"] == "₹909.00"
        assert body["balance_display"] == "₹2121.00"

    def test_a_service_with_no_deposit_quotes_zero(self, client):
        provider = make_profile()
        service = make_service(provider, price=20000, deposit_percent=0)
        client_, token = logged_in(make_user())

        body = client_.post(
            f"{BOOKINGS}quote/",
            {
                "provider": provider.id,
                "services": [service.id],
                "starts_at": next_slot(hour=12).isoformat(),
            },
            content_type="application/json",
            **auth_header(token),
        ).json()

        assert body["deposit"] == 0
        assert body["balance"] == body["total"]


# ---------------------------------------------------------------------------
# Charging
# ---------------------------------------------------------------------------


class TestChargingADeposit:
    @pytest.fixture(autouse=True)
    def _razorpay(self, monkeypatch):
        from payments import views

        monkeypatch.setattr(views, "credentials_configured", lambda: True)
        monkeypatch.setattr(
            views,
            "create_order",
            lambda **kwargs: {
                "id": "order_abc",
                "key_id": "rzp_test",
                "amount": kwargs["amount"],
                "currency": kwargs["currency"],
                "_kwargs": kwargs,
            },
        )

    def test_the_first_charge_asks_for_the_deposit_not_the_total(self, client):
        booking, customer, _provider = booking_with_deposit()
        client_, token = logged_in(customer)

        response = client_.post(
            f"{PAYMENTS}orders/",
            {"booking": booking.reference},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 201, response.content
        payment = Payment.objects.filter(booking=booking, kind=PaymentKind.DEPOSIT).first()
        assert payment is not None
        assert payment.amount == booking.deposit

    def test_the_balance_charges_only_what_is_left(self, client):
        booking, customer, _provider = booking_with_deposit()
        Payment.objects.create(
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            razorpay_order_id="order_dep",
            amount=booking.deposit,
            status=PaymentStatus.CAPTURED,
        )
        client_, token = logged_in(customer)

        client_.post(
            f"{PAYMENTS}orders/?kind=balance",
            {"booking": booking.reference},
            content_type="application/json",
            **auth_header(token),
        )

        payment = Payment.objects.filter(booking=booking, kind=PaymentKind.BALANCE).first()
        assert payment is not None
        assert payment.amount == booking.balance

    def test_a_second_deposit_is_refused(self, client):
        booking, customer, _provider = booking_with_deposit()
        Payment.objects.create(
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            razorpay_order_id="order_dep",
            amount=booking.deposit,
            status=PaymentStatus.CAPTURED,
        )
        client_, token = logged_in(customer)

        response = client_.post(
            f"{PAYMENTS}orders/?kind=deposit",
            {"booking": booking.reference},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_nothing_is_asked_for_once_the_booking_is_settled(self, client):
        booking, customer, _provider = booking_with_deposit()
        for kind, amount in (
            (PaymentKind.DEPOSIT, booking.deposit),
            (PaymentKind.BALANCE, booking.balance),
        ):
            Payment.objects.create(
                booking=booking,
                kind=kind,
                razorpay_order_id=f"order_{kind}",
                amount=amount,
                status=PaymentStatus.CAPTURED,
            )
        client_, token = logged_in(customer)

        response = client_.post(
            f"{PAYMENTS}orders/",
            {"booking": booking.reference},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_the_amount_comes_from_the_server_not_the_request(self, client):
        booking, customer, _provider = booking_with_deposit()
        client_, token = logged_in(customer)

        response = client_.post(
            f"{PAYMENTS}orders/",
            # The amount the old API let a client dictate.
            {"booking": booking.reference, "amount": 1},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 201, response.content
        payment = Payment.objects.filter(booking=booking).first()
        assert payment.amount == booking.deposit


# ---------------------------------------------------------------------------
# Data integrity
# ---------------------------------------------------------------------------


class TestConstraints:
    def test_the_deposit_never_exceeds_the_total(self, client):
        provider = make_profile()
        service = make_service(provider, price=100000, deposit_percent=100)
        client_, token = logged_in(make_user())

        body = client_.post(
            f"{BOOKINGS}new/",
            {
                "provider": provider.id,
                "services": [service.id],
                "starts_at": next_slot(hour=12).isoformat(),
            },
            content_type="application/json",
            **auth_header(token),
        ).json()

        assert body["deposit"] == body["total"]
        assert body["balance"] == 0

    def test_two_live_charges_of_the_same_kind_are_impossible(self):
        booking, *_ = booking_with_deposit()
        Payment.objects.create(
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            razorpay_order_id="order_1",
            amount=booking.deposit,
            status=PaymentStatus.CREATED,
        )

        from django.db.utils import IntegrityError

        with pytest.raises(IntegrityError):
            Payment.objects.create(
                booking=booking,
                kind=PaymentKind.DEPOSIT,
                razorpay_order_id="order_2",
                amount=booking.deposit,
                status=PaymentStatus.CREATED,
            )

    def test_a_refunded_charge_does_not_block_a_new_one(self):
        # A deposit that was refunded and then retaken is a real sequence; the
        # constraint is only about *live* charges.
        booking, *_ = booking_with_deposit()
        Payment.objects.create(
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            razorpay_order_id="order_1",
            amount=booking.deposit,
            status=PaymentStatus.CAPTURED,
        )
        payment = Payment.objects.get(razorpay_order_id="order_1")
        payment.status = PaymentStatus.REFUNDED
        payment.save(update_fields=["status"])

        Payment.objects.create(
            booking=booking,
            kind=PaymentKind.DEPOSIT,
            razorpay_order_id="order_2",
            amount=booking.deposit,
            status=PaymentStatus.CREATED,
        )
