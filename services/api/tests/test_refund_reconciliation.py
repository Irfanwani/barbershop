"""Two bugs in how refunded money is counted.

Both were found after P1.3 shipped, and both are the kind that do not fail
loudly. The code ran, the refund succeeded, the tests passed — and a customer
was still being told they owed money they had already handed back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
from django.utils import timezone

from bookings.models import Booking
from payments.models import Payment, PaymentStatus
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
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


@dataclass
class Session:
    user: Any
    client: Any
    token: str

    def auth(self) -> dict:
        return auth_header(self.token)


def a_customer(label: str = "customer") -> Session:
    user = make_user(_next_name(label))
    client, token = logged_in(user)
    return Session(user=user, client=client, token=token)


def a_paid_booking(deposit: bool = True):
    """A booking with a captured payment against it."""
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner)
    service = make_service(profile, price=40000, deposit_percent=50 if deposit else 0)

    customer = a_customer()
    starts_at = (timezone.localtime() + __import__("datetime").timedelta(days=3)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )

    response = customer.client.post(
        f"{V1}/bookings/new/",
        {
            "provider": profile.pk,
            "services": [service.pk],
            "starts_at": starts_at.isoformat(),
        },
        **customer.auth(),
    )
    assert response.status_code == 201, response.data
    booking = Booking.objects.get(reference=response.data["reference"])

    payment = Payment.objects.create(
        booking=booking,
        kind="deposit",
        amount=booking.deposit,
        currency="INR",
        status=PaymentStatus.CAPTURED,
        razorpay_payment_id=f"pay_{_next_name('p')}",
    )
    return customer, profile, booking, payment


class TestMoneyThatWentBack:
    def test_a_partial_refund_reduces_what_has_been_paid(self):
        """The bug: the booking still looked fully paid after money returned."""
        _customer, _profile, booking, payment = a_paid_booking()
        paid = booking.amount_paid

        payment.refunded_amount = payment.amount // 2
        payment.save(update_fields=["refunded_amount"])

        assert booking.amount_paid == paid - payment.amount // 2
        assert booking.amount_paid < booking.total
        assert booking.amount_due == booking.total - (paid - payment.amount // 2)

    def test_a_partial_refund_leaves_the_booking_unpaid(self):
        _customer, _profile, booking, payment = a_paid_booking()
        assert booking.is_paid is False

        payment.refunded_amount = payment.amount // 2
        payment.save(update_fields=["refunded_amount"])

        assert booking.is_paid is False

    def test_a_full_refund_owes_nothing(self):
        _customer, _profile, booking, payment = a_paid_booking()
        payment.refunded_amount = payment.amount
        payment.save(update_fields=["refunded_amount"])

        assert booking.amount_paid == 0
        assert booking.amount_due == booking.total

    def test_amount_paid_is_never_negative(self):
        """A gateway-side adjustment could over-refund. Do not owe the shop."""
        _customer, _profile, booking, payment = a_paid_booking()
        payment.refunded_amount = payment.amount + 5000
        payment.save(update_fields=["refunded_amount"])

        assert booking.amount_paid == 0
        assert booking.amount_due == booking.total

    def test_a_refunded_deposit_is_not_still_held(self):
        """The bug: the shop was never asked for the deposit again."""
        _customer, _profile, booking, payment = a_paid_booking(deposit=True)
        assert booking.has_captured_deposit is True
        assert booking.requires_deposit is False

        payment.refunded_amount = payment.amount
        payment.status = PaymentStatus.REFUNDED
        payment.save(update_fields=["refunded_amount", "status"])

        assert booking.has_captured_deposit is False
        assert booking.requires_deposit is True

    def test_a_partly_refunded_deposit_is_still_held(self):
        _customer, _profile, booking, payment = a_paid_booking(deposit=True)
        payment.refunded_amount = payment.amount - 1
        payment.save(update_fields=["refunded_amount"])

        assert booking.has_captured_deposit is True


class TestTheRefundWebhook:
    """A refund is initiated synchronously and settles asynchronously.

    The gap between the two is where a customer who has been made whole ends
    up still being shown as owing money that has already gone.
    """

    def _signed_post(self, client, event: str, entity: dict):
        from payments.services import sign_webhook_payload

        body = {"event": event, "payload": {"refund": {"entity": entity}}}
        raw = json.dumps(body).encode()
        return client.post(
            f"{V1}/payments/webhook/",
            data=raw,
            content_type="application/json",
            headers={"X-Razorpay-Signature": sign_webhook_payload(raw)},
        )

    def test_a_processed_refund_is_settled(self):
        _customer, _profile, booking, payment = a_paid_booking()
        payment.refund_id = "rfnd_123"
        payment.save(update_fields=["refund_id"])

        response = self._signed_post(
            a_customer("bystander").client,
            "refund.processed",
            {"id": "rfnd_123", "status": "processed", "amount": payment.amount},
        )

        assert response.status_code == 200
        payment.refresh_from_db()
        assert payment.refunded_amount == payment.amount
        assert payment.status == PaymentStatus.REFUNDED
        assert booking.amount_paid == 0

    def test_a_failed_refund_keeps_the_money_owed(self):
        _customer, _profile, booking, payment = a_paid_booking()
        payment.refund_id = "rfnd_456"
        payment.save(update_fields=["refund_id"])

        self._signed_post(
            a_customer("bystander2").client,
            "refund.failed",
            {"id": "rfnd_456", "status": "failed", "error_description": "bank declined"},
        )

        payment.refresh_from_db()
        assert payment.refunded_amount == 0
        assert "bank declined" in payment.failure_reason
        assert booking.amount_paid == payment.amount

    def test_a_successful_refund_clears_an_earlier_failure(self):
        """Otherwise a booking reads as refunded *and* failed."""
        _customer, _profile, _booking, payment = a_paid_booking()
        payment.refund_id = "rfnd_789"
        payment.failure_reason = "bank declined"
        payment.save(update_fields=["refund_id", "failure_reason"])

        self._signed_post(
            a_customer("bystander3").client,
            "refund.processed",
            {"id": "rfnd_789", "status": "processed", "amount": payment.amount},
        )

        payment.refresh_from_db()
        assert payment.failure_reason == ""

    def test_an_unknown_refund_is_acknowledged_not_retried(self):
        """It will never become known, and a retry storm helps nobody."""
        response = self._signed_post(
            a_customer("bystander4").client,
            "refund.processed",
            {"id": "rfnd_unknown", "status": "processed"},
        )

        assert response.status_code == 200
        assert response.json()["handled"] is False

    def test_an_unsigned_refund_event_is_refused(self):
        _customer, _profile, _booking, payment = a_paid_booking()
        before = payment.refunded_amount

        response = a_customer("thief").client.post(
            f"{V1}/payments/webhook/",
            data=json.dumps(
                {
                    "event": "refund.processed",
                    "payload": {"refund": {"entity": {"id": "rfnd_x", "status": "processed"}}},
                }
            ),
            content_type="application/json",
            headers={"X-Razorpay-Signature": "not-a-signature"},
        )

        assert response.status_code == 400
        payment.refresh_from_db()
        assert payment.refunded_amount == before
