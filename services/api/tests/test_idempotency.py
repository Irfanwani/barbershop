"""Retrying must not charge twice.

A client on a flaky connection retries. On a payment endpoint that is not
merely wasteful: a retried verify is a second chance to capture, and a payment
that appears twice on a statement is the kind of thing a customer does not
forgive. The mobile app currently disables mutation retries entirely because
of this — fixing it is what lets them turn back on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from payments.idempotency import fingerprint
from payments.models import IdempotencyRecord, Payment, PaymentStatus
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

    def as_(self, key: str) -> dict:
        return {"HTTP_IDEMPOTENCY_KEY": key, **self.auth()}


def a_customer() -> Session:
    user = make_user(_next_name("customer"))
    make_profile(user)
    client, token = logged_in(user)
    return Session(user=user, client=client, token=token)


def an_unpaid_booking():
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner)
    service = make_service(profile, price=40000, deposit_percent=50)

    customer = a_customer()
    from datetime import timedelta

    from django.utils import timezone

    starts_at = (timezone.localtime() + timedelta(days=3)).replace(
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

    booking = response.data
    payment = Payment.objects.filter(
        booking__customer=customer.user, booking__reference=booking["reference"]
    ).first()
    if payment is None:
        from bookings.models import Booking

        found = Booking.objects.get(reference=booking["reference"])
        payment = Payment.objects.create(
            booking=found,
            kind="deposit",
            amount=found.deposit,
            currency="INR",
            status=PaymentStatus.CREATED,
            razorpay_order_id=f"order_{uuid.uuid4().hex[:12]}",
        )
    return customer, booking, payment


@pytest.fixture(autouse=True)
def a_gateway_that_captures(monkeypatch):
    """The gateway agrees, and the signature is genuine.

    Without this the endpoint refuses before it does any work, nothing is ever
    recorded, and the tests below would pass for the wrong reason.
    """
    import payments.views as views

    monkeypatch.setattr(views, "verify_payment_signature", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        views, "fetch_payment", lambda payment_id: {"id": payment_id, "status": "captured"}
    )


#: A retry resends the body it sent the first time. A helper that invented a
#: new payment id on every call would be testing a different request each time,
#: which the server quite correctly refuses.
PAYMENT_ID = f"pay_{uuid.uuid4().hex[:12]}"


def verify(customer: Session, payment: Payment, key: str | None = None):
    body = {
        "razorpay_order_id": payment.razorpay_order_id,
        "razorpay_payment_id": PAYMENT_ID,
        "razorpay_signature": "sig",
    }
    headers = customer.as_(key) if key else customer.auth()
    return customer.client.post(f"{V1}/payments/verify/", body, **headers)


class TestTheFingerprint:
    def test_key_order_does_not_change_the_fingerprint(self):
        """A client is not obliged to serialise a dict consistently."""
        assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})

    def test_a_different_body_does(self):
        assert fingerprint({"a": 1}) != fingerprint({"a": 2})


class TestRetrying:
    def test_without_a_key_nothing_changes(self):
        """The feature adds no requirement to any client."""
        customer, _booking, payment = an_unpaid_booking()

        assert verify(customer, payment).status_code in (200, 400)
        assert IdempotencyRecord.objects.count() == 0

    def test_two_identical_calls_create_one_capture(self):
        customer, _booking, payment = an_unpaid_booking()
        key = str(uuid.uuid4())
        body_key = payment.razorpay_order_id

        first = verify(customer, payment, key)
        second = verify(customer, payment, key)

        assert first.status_code == second.status_code
        assert first.data == second.data
        assert IdempotencyRecord.objects.filter(key=key).count() == 1
        assert body_key == payment.razorpay_order_id

    def test_the_replayed_response_is_identical(self):
        customer, _booking, payment = an_unpaid_booking()
        key = str(uuid.uuid4())

        first = verify(customer, payment, key)
        second = verify(customer, payment, key)

        assert first.data == second.data
        assert first.status_code == second.status_code

    def test_a_retry_captures_the_payment_only_once(self):
        customer, _booking, payment = an_unpaid_booking()
        key = str(uuid.uuid4())

        verify(customer, payment, key)
        verify(customer, payment, key)
        verify(customer, payment, key)

        assert payment.captured_count_for_order() == 1

    def test_the_key_is_recorded_against_the_account(self):
        customer, _booking, payment = an_unpaid_booking()
        key = str(uuid.uuid4())
        verify(customer, payment, key)

        record = IdempotencyRecord.objects.get(key=key)
        assert record.user_id == customer.user.pk
        assert record.endpoint == "payments.verify"


class TestTheSameKeyWithADifferentRequest:
    def test_it_is_refused(self):
        """Otherwise the client is handed back somebody else's receipt."""
        customer, _booking, payment = an_unpaid_booking()
        key = str(uuid.uuid4())

        first = verify(customer, payment, key)
        assert first.status_code in (200, 400)

        # Same key, different payment id — a different request.
        response = customer.client.post(
            f"{V1}/payments/verify/",
            {
                "razorpay_order_id": payment.razorpay_order_id,
                "razorpay_payment_id": "pay_something_else",
                "razorpay_signature": "sig",
            },
            **customer.as_(key),
        )

        assert response.status_code == 409

    def test_the_conflict_names_itself(self):
        customer, _booking, payment = an_unpaid_booking()
        key = str(uuid.uuid4())
        verify(customer, payment, key)

        response = customer.client.post(
            f"{V1}/payments/verify/",
            {
                "razorpay_order_id": payment.razorpay_order_id,
                "razorpay_payment_id": "pay_other",
                "razorpay_signature": "sig",
            },
            **customer.as_(key),
        )

        assert response.json()["error"]["code"] == "idempotency_conflict"


class TestTwoPeopleOnOneDevice:
    def test_their_keys_do_not_collide(self):
        one, _booking_a, payment_a = an_unpaid_booking()
        two, _booking_b, payment_b = an_unpaid_booking()
        key = str(uuid.uuid4())

        # Same generated key, two accounts, two orders.
        a = verify(one, payment_a, key)
        b = verify(two, payment_b, key)

        assert a.status_code != 409
        assert b.status_code != 409
        assert IdempotencyRecord.objects.filter(key=key).count() == 2


class TestOnlySuccessesAreRecorded:
    def test_a_failure_can_be_retried(self):
        """A client that genuinely failed should be free to try again."""
        customer, _booking, _payment = an_unpaid_booking()
        key = str(uuid.uuid4())

        # No such order on this account: a business failure, not a retry.
        response = customer.client.post(
            f"{V1}/payments/verify/",
            {
                "razorpay_order_id": "order_nope",
                "razorpay_payment_id": "pay_nope",
                "razorpay_signature": "sig",
            },
            **customer.as_(key),
        )

        assert response.status_code >= 400
        assert not IdempotencyRecord.objects.filter(key=key).exists()


class TestAnAncientKey:
    def test_is_not_replayed(self):
        """A client that keys per attempt rather than per operation is not
        locked out of ever using the endpoint again."""
        from datetime import timedelta

        from django.utils import timezone

        customer, _booking, payment = an_unpaid_booking()
        key = str(uuid.uuid4())
        verify(customer, payment, key)

        IdempotencyRecord.objects.filter(key=key).update(
            created_at=timezone.now() - timedelta(days=30)
        )

        response = verify(customer, payment, key)
        assert response.status_code != 409
