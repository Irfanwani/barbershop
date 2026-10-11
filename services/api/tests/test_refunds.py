"""Refunds.

The scaffolding existed from day one and never ran — `REFUNDED`, `refunded_at`
and `refund_id` were all on the model with nothing writing them — so a
cancelled-and-paid booking had no way to give the money back, and the
late-cancel fee had nowhere to go.

The properties worth defending are the ones that protect the shop's money: a
refund can never exceed what was taken, and a completed appointment cannot be
refunded silently.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from core.money import compute_deposit
from payments import refunds as refund_module
from payments.choices import PaymentKind
from payments.models import Payment, PaymentStatus
from payments.refunds import (
    GatewayUnavailable,
    RefundError,
    refund_booking_deposit,
    refund_booking_payment,
    refundable,
    send_refund,
)
from tests.factories import auth_header, logged_in, make_user

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
PAYMENTS = f"{V1}/payments/"


@pytest.fixture(autouse=True)
def razorpay(monkeypatch):
    """Record what was asked of the gateway instead of asking it."""
    sent: list[dict] = []

    def _create_refund(*, payment_id, amount, notes=None):
        sent.append({"payment_id": payment_id, "amount": amount, "notes": notes})
        return {"id": f"rfnd_{len(sent)}"}

    monkeypatch.setattr("payments.services.create_refund", _create_refund, raising=False)
    return sent


def paid_booking(*, status=BookingStatus.CONFIRMED, deposit_percent=30, price=300000):
    from tests.factories import make_profile, make_service

    provider = make_profile()
    service = make_service(provider, price=price, deposit_percent=deposit_percent)
    customer = make_user()
    total = price + 3000
    deposit, balance = compute_deposit(total, deposit_percent)

    starts_at = timezone.now() + timedelta(hours=48)
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
        cancellation_window_hours=24,
        late_cancel_fee_percent=50,
        late_cancel_fee=compute_deposit(deposit, 50)[0],
        status=status,
    )
    booking.items.create(service=service, name=service.name, unit_price=price, quantity=1)

    for kind, amount in ((PaymentKind.DEPOSIT, deposit), (PaymentKind.BALANCE, balance)):
        Payment.objects.create(
            booking=booking,
            kind=kind,
            razorpay_order_id=f"order_{kind}",
            razorpay_payment_id=f"pay_{kind}",
            amount=amount,
            status=PaymentStatus.CAPTURED,
        )
    booking.refresh_from_db()
    return booking


# ---------------------------------------------------------------------------
# The refund itself
# ---------------------------------------------------------------------------


class TestSendRefund:
    def test_refunds_what_was_taken(self, razorpay):
        booking = paid_booking()
        payment = booking.payments.get(kind=PaymentKind.BALANCE)

        send_refund(payment)

        assert razorpay[0]["amount"] == payment.amount
        assert razorpay[0]["payment_id"] == "pay_balance"

    def test_records_the_gateway_refund_id(self, razorpay):
        payment = paid_booking().payments.get(kind=PaymentKind.BALANCE)

        send_refund(payment)

        payment.refresh_from_db()
        assert payment.refund_id == "rfnd_1"

    def test_a_full_refund_marks_the_payment_refunded(self, razorpay):
        payment = paid_booking().payments.get(kind=PaymentKind.BALANCE)

        send_refund(payment)

        payment.refresh_from_db()
        assert payment.status == PaymentStatus.REFUNDED
        assert payment.refunded_at is not None

    def test_a_partial_refund_leaves_it_captured(self, razorpay):
        # A shop refunding half a balance has not finished.
        payment = paid_booking().payments.get(kind=PaymentKind.BALANCE)

        send_refund(payment, payment.amount // 2)

        payment.refresh_from_db()
        assert payment.status == PaymentStatus.CAPTURED
        assert payment.refunded_amount == payment.amount // 2

    def test_refunds_accumulate(self, razorpay):
        payment = paid_booking().payments.get(kind=PaymentKind.BALANCE)

        send_refund(payment, 1000)
        send_refund(payment, 2000)

        payment.refresh_from_db()
        assert payment.refunded_amount == 3000
        assert payment.status == PaymentStatus.CAPTURED

    def test_cannot_refund_more_than_was_paid(self, razorpay):
        # Recording a refund larger than the payment would let a shop mint money
        # out of a cancellation.
        payment = paid_booking().payments.get(kind=PaymentKind.BALANCE)

        with pytest.raises(RefundError):
            send_refund(payment, payment.amount * 2)

        assert razorpay == []

    def test_cannot_refund_twice_in_full(self, razorpay):
        payment = paid_booking().payments.get(kind=PaymentKind.BALANCE)
        send_refund(payment)

        with pytest.raises(RefundError):
            send_refund(payment)

    def test_refundable_shrinks_as_money_goes_back(self, razorpay):
        payment = paid_booking().payments.get(kind=PaymentKind.BALANCE)

        assert refundable(payment) == payment.amount
        send_refund(payment, 5000)
        assert refundable(payment) == payment.amount - 5000

    def test_an_uncaptured_payment_is_not_refundable(self):
        booking = paid_booking()
        payment = booking.payments.get(kind=PaymentKind.DEPOSIT)
        payment.status = PaymentStatus.FAILED
        payment.save(update_fields=["status"])

        assert refundable(payment) == 0

    def test_cash_is_settled_without_asking_the_gateway(self, razorpay):
        # The money was in the cash box. There is nothing to send.
        booking = paid_booking()
        payment = booking.payments.get(kind=PaymentKind.BALANCE)
        payment.method = Payment.PaymentMethod.CASH
        payment.razorpay_payment_id = ""
        payment.save(update_fields=["method", "razorpay_payment_id"])

        send_refund(payment)

        assert razorpay == []
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.REFUNDED

    def test_a_gateway_outage_is_distinguishable(self, monkeypatch):
        # "Try again" and "this will never work" need different wording.
        payment = paid_booking().payments.get(kind=PaymentKind.BALANCE)

        def boom(**kwargs):
            raise ConnectionError("gateway down")

        monkeypatch.setattr("payments.services.create_refund", boom)

        with pytest.raises(GatewayUnavailable):
            send_refund(payment)


# ---------------------------------------------------------------------------
# Refunding a booking
# ---------------------------------------------------------------------------


class TestRefundBooking:
    def test_a_provider_can_refund_the_balance(self, razorpay):
        booking = paid_booking()
        client, token = logged_in(booking.provider.user)

        response = client.post(
            f"{PAYMENTS}bookings/{booking.reference}/refund/",
            {"reason": "Could not do the colour"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200, response.content
        booking.refresh_from_db()
        assert booking.amount_paid == booking.deposit

    def test_refunding_the_balance_takes_it_off_what_is_owed(self, razorpay):
        booking = paid_booking()
        client, token = logged_in(booking.provider.user)

        client.post(
            f"{PAYMENTS}bookings/{booking.reference}/refund/",
            {},
            content_type="application/json",
            **auth_header(token),
        )

        booking.refresh_from_db()
        assert booking.amount_due == booking.balance

    def test_a_customer_cannot_refund_their_own_booking(self, razorpay):
        booking = paid_booking()
        client, token = logged_in(booking.customer)

        response = client.post(
            f"{PAYMENTS}bookings/{booking.reference}/refund/",
            {},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code in (403, 404)
        booking.refresh_from_db()
        assert booking.amount_paid == booking.total

    def test_a_shop_cannot_refund_another_shops_booking(self, razorpay):
        from tests.factories import make_profile, make_provider_user

        booking = paid_booking()
        stranger = make_provider_user()
        make_profile(stranger)
        client, token = logged_in(stranger)

        response = client.post(
            f"{PAYMENTS}bookings/{booking.reference}/refund/",
            {},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 404

    def test_a_completed_appointment_cannot_be_refunded_silently(self, razorpay):
        # The service was had. Giving the money back for it is a decision the
        # shop should not be able to make without saying so.
        booking = paid_booking(status=BookingStatus.COMPLETED)
        client, token = logged_in(booking.provider.user)

        response = client.post(
            f"{PAYMENTS}bookings/{booking.reference}/refund/",
            {},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert razorpay == []

    def test_an_unpaid_balance_cannot_be_refunded(self, razorpay):
        booking = paid_booking()
        Payment.objects.filter(booking=booking, kind=PaymentKind.BALANCE).update(
            status=PaymentStatus.FAILED
        )
        booking.refresh_from_db()
        client, token = logged_in(booking.provider.user)

        response = client.post(
            f"{PAYMENTS}bookings/{booking.reference}/refund/",
            {},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Cancellation refunds
# ---------------------------------------------------------------------------


class TestCancellationRefund:
    def test_a_prompt_cancellation_refunds_the_deposit_in_full(self, razorpay):
        booking = paid_booking()
        # 24h window, so 200 hours out is comfortably free.
        booking.starts_at = timezone.now() + timedelta(hours=200)
        booking.ends_at = booking.starts_at + timedelta(hours=2)
        booking.save()

        from bookings.policy import apply_cancellation

        outcome = apply_cancellation(booking, by_provider=False, reason="plans changed")
        refund_booking_deposit(booking, forfeited=outcome.deposit_forfeited)

        booking.refresh_from_db()
        deposit = booking.payments.get(kind=PaymentKind.DEPOSIT)
        assert deposit.refunded_amount == booking.deposit

    def test_a_late_cancellation_keeps_the_agreed_slice(self, razorpay):
        from bookings.policy import apply_cancellation

        booking = paid_booking()
        # Two hours out against a 24-hour window: genuinely late.
        booking.starts_at = timezone.now() + timedelta(hours=2)
        booking.ends_at = booking.starts_at + timedelta(hours=2)
        booking.save()

        outcome = apply_cancellation(booking, by_provider=False, reason="late")
        assert outcome.deposit_forfeited == booking.late_cancel_fee
        refund_booking_deposit(booking, forfeited=outcome.deposit_forfeited)

        booking.refresh_from_db()
        deposit = booking.payments.get(kind=PaymentKind.DEPOSIT)
        assert deposit.refunded_amount == booking.deposit - booking.late_cancel_fee

    def test_a_provider_cancellation_always_refunds_in_full(self, razorpay):
        from bookings.policy import apply_cancellation

        booking = paid_booking()
        outcome = apply_cancellation(booking, by_provider=True, reason="ill")

        assert outcome.deposit_forfeited == 0
        refund_booking_deposit(booking, forfeited=outcome.deposit_forfeited)

        booking.refresh_from_db()
        deposit = booking.payments.get(kind=PaymentKind.DEPOSIT)
        assert deposit.refunded_amount == booking.deposit

    def test_cancelling_through_the_endpoint_moves_the_money(self, razorpay):
        booking = paid_booking()
        client, token = logged_in(booking.customer)

        response = client.post(
            f"{V1}/bookings/{booking.reference}/cancel/",
            {"reason": "Something came up"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        assert response.data["cancellation"]["deposit_refundable"] > 0
        booking.refresh_from_db()
        assert booking.payments.get(kind=PaymentKind.DEPOSIT).refunded_amount > 0

    def test_the_balance_is_refunded_when_the_deposit_is_forfeited(self, razorpay):
        # Nothing useful comes back from the deposit, so the money the customer
        # actually wants has to come from the balance.
        from bookings.policy import apply_cancellation

        booking = paid_booking()
        booking.starts_at = timezone.now() + timedelta(hours=2)
        booking.ends_at = booking.starts_at + timedelta(hours=2)
        booking.save()
        apply_cancellation(booking, by_provider=False, reason="late")
        refund_booking_deposit(booking, forfeited=booking.late_cancel_fee)
        refund_booking_payment(booking, reason="Deposit forfeited")

        booking.refresh_from_db()
        assert booking.payments.get(kind=PaymentKind.BALANCE).refunded_amount == booking.balance

    def test_a_gateway_outage_does_not_undo_the_cancellation(self, monkeypatch, razorpay):
        # The booking is cancelled either way. A slow gateway should not make
        # the customer think it did not happen.
        booking = paid_booking()
        client, token = logged_in(booking.customer)

        def boom(**kwargs):
            raise ConnectionError("gateway down")

        monkeypatch.setattr("payments.services.create_refund", boom)

        response = client.post(
            f"{V1}/bookings/{booking.reference}/cancel/",
            {"reason": "Something came up"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        booking.refresh_from_db()
        assert booking.status == BookingStatus.CANCELLED_BY_CUSTOMER
        assert "could not start the refund" in response.data["cancellation"]["message"]

    def test_an_uncaptured_deposit_refunds_nothing(self, razorpay):
        from bookings.policy import apply_cancellation

        booking = paid_booking()
        booking.starts_at = timezone.now() + timedelta(hours=2)
        booking.ends_at = booking.starts_at + timedelta(hours=2)
        booking.save()
        Payment.objects.filter(booking=booking, kind=PaymentKind.DEPOSIT).update(
            status=PaymentStatus.FAILED
        )
        booking.refresh_from_db()
        apply_cancellation(booking, by_provider=False, reason="late")

        assert refund_booking_deposit(booking, forfeited=0) == []


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


class TestReconciliation:
    def test_a_settled_refund_is_recorded(self):
        payment = paid_booking().payments.get(kind=PaymentKind.BALANCE)
        payment.status = PaymentStatus.CAPTURED
        payment.refunded_amount = payment.amount
        payment.save()

        refund_module.reconcile(payment, {"status": "processed"})

        payment.refresh_from_db()
        assert payment.status == PaymentStatus.REFUNDED

    def test_a_failed_refund_says_why(self):
        payment = paid_booking().payments.get(kind=PaymentKind.BALANCE)

        refund_module.reconcile(payment, {"status": "failed", "error_description": "no balance"})

        payment.refresh_from_db()
        assert "no balance" in payment.failure_reason

    def test_a_partial_refund_stays_captured_when_settled(self):
        payment = paid_booking().payments.get(kind=PaymentKind.BALANCE)
        payment.refunded_amount = 1000
        payment.save()

        refund_module.reconcile(payment, {"status": "processed"})

        # Still money owed on this booking.
        payment.refresh_from_db()
        assert payment.status == PaymentStatus.CAPTURED
