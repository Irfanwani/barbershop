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

from bookings.models import Booking, BookingStatus
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


def another_unpaid_booking_for(customer: Session):
    """A second appointment for someone who already has one.

    Same account on purpose: keys are namespaced per user, so reusing a key
    across two different accounts is not the case under test.
    """
    from datetime import timedelta

    from django.utils import timezone

    from bookings.models import Booking

    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner)
    service = make_service(profile, price=40000, deposit_percent=50)

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

    booking = Booking.objects.get(reference=response.data["reference"])
    payment = Payment.objects.create(
        booking=booking,
        kind="deposit",
        amount=booking.deposit,
        currency="INR",
        status=PaymentStatus.CREATED,
        razorpay_order_id=f"order_{uuid.uuid4().hex[:12]}",
    )
    return booking, payment


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


class TestAnExpiredKeyIsNotARecord:
    """The previous version of this file asserted only `!= 409`.

    That is not the same as "the request was honoured". A key past its TTL fell
    through to the view, the view did the work, and *then* the insert collided
    with the old row and replayed the original response. So an expired key did
    the work twice and reported the first result - a second capture whose
    receipt the caller never saw.
    """

    def test_the_old_response_is_not_replayed(self):
        from datetime import timedelta

        from django.utils import timezone

        customer, _booking, payment = an_unpaid_booking()
        key = str(uuid.uuid4())
        first = verify(customer, payment, key)

        IdempotencyRecord.objects.filter(key=key).update(
            created_at=timezone.now() - timedelta(days=30)
        )

        second = verify(customer, payment, key)

        assert second.data == first.data
        assert Payment.objects.filter(pk=payment.pk).count() == 1

    def test_reusing_it_for_a_different_payment_does_not_return_the_first_receipt(self):
        """The dangerous case.

        Same key, expired, but a genuinely different payment. Handing back the
        first booking's receipt would tell the customer their second payment
        succeeded while it had actually been captured separately - or not at
        all.
        """
        from datetime import timedelta

        from django.utils import timezone

        customer, _first_booking, first_payment = an_unpaid_booking()
        key = str(uuid.uuid4())
        verify(customer, first_payment, key)

        second_booking, second_payment = another_unpaid_booking_for(customer)

        IdempotencyRecord.objects.filter(key=key).update(
            created_at=timezone.now() - timedelta(days=30)
        )

        response = verify(customer, second_payment, key)

        assert response.status_code == 200
        assert response.data["id"] == second_payment.pk, "replayed a receipt for the first payment"
        assert response.data["id"] != first_payment.pk
        assert response.data["booking"] == second_booking.pk
        assert Payment.objects.get(pk=second_payment.pk).status == PaymentStatus.CAPTURED


class TestTheRaceTheRecordCannotSee:
    """Two requests, one key, both arriving before either has finished.

    The record was written *after* the view ran, so a second request that
    arrived during the first found nothing, ran the view again, and both
    requests tried to capture. The winner of the insert was simply whoever
    committed first; the other response was discarded and the money still
    moved twice.
    """

    def test_a_request_arriving_mid_flight_does_not_do_the_work_again(self):
        import payments.views as views

        customer, _booking, payment = an_unpaid_booking()
        key = str(uuid.uuid4())

        captures = 0
        reentrant_response = {}

        real_capture = views.capture

        def capture_and_reenter(*args, **kwargs):
            """Capture, then fire a second request with the same key.

            Re-entering from inside the first request puts the second one
            precisely in the window that matters: after the first has decided
            to do the work, before it has recorded anything.
            """
            nonlocal captures
            captures += 1
            result = real_capture(*args, **kwargs)
            if captures == 1:
                reentrant_response["value"] = verify(customer, payment, key)
            return result

        views.capture = capture_and_reenter
        try:
            outer = verify(customer, payment, key)
        finally:
            views.capture = real_capture

        assert outer.status_code == 200
        assert captures == 1, "the payment was captured twice"
        assert reentrant_response["value"].status_code in (200, 409)

    def test_a_second_capture_never_lands(self):
        """Even if both get through, the money must move once.

        Belt and braces: the guard above should stop the second request
        entirely, and this checks the thing that would be catastrophic on its
        own.
        """
        customer, _booking, payment = an_unpaid_booking()
        key = str(uuid.uuid4())

        verify(customer, payment, key)
        verify(customer, payment, key)

        booking = Booking.objects.get(pk=payment.booking_id)
        assert Payment.objects.get(pk=payment.pk).status == PaymentStatus.CAPTURED
        # One payment, captured once, and the booking moved forward exactly once.
        assert Payment.objects.filter(booking=booking, status=PaymentStatus.CAPTURED).count() == 1
        assert booking.status != BookingStatus.PENDING_PAYMENT


class TestTheWritesThatWereNotGuarded:
    """The app sends a key on every write and retries every mutation.

    Two of the three endpoints it retries were ignoring the key entirely, so a
    retry created a second booking, or a second Razorpay order. The header was
    travelling all the way to the server and being dropped on the floor.
    """

    def test_a_retried_booking_does_not_book_twice(self):
        from datetime import timedelta

        from django.utils import timezone

        from bookings.models import Booking
        from tests.factories import make_profile, make_provider_user, make_service

        owner = make_provider_user(_next_name("shop"))
        profile = make_profile(owner)
        service = make_service(profile, price=40000)

        customer = a_customer()
        starts_at = (timezone.localtime() + timedelta(days=3)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        body = {
            "provider": profile.pk,
            "services": [service.pk],
            "starts_at": starts_at.isoformat(),
        }
        key = str(uuid.uuid4())

        first = customer.client.post(f"{V1}/bookings/new/", body, **customer.as_(key))
        second = customer.client.post(f"{V1}/bookings/new/", body, **customer.as_(key))

        assert first.status_code == 201
        assert second.status_code == first.status_code
        assert second.data["reference"] == first.data["reference"]
        assert Booking.objects.filter(customer=customer.user, provider=profile).count() == 1, (
            "the retry booked the same slot twice"
        )

    def test_a_retried_order_does_not_create_two(self, monkeypatch):
        from datetime import timedelta

        from django.utils import timezone

        import payments.views as views

        # No test existed for order creation at all, so the gateway stub lives
        # here. Each call gets a distinct order id, which is what makes the
        # assertion meaningful: if the key were ignored, the retry would come
        # back with a second, different order.
        issued = 0

        def fake_create_order(*args, **kwargs):
            nonlocal issued
            issued += 1
            return {
                "id": f"order_{issued}",
                "key_id": "rzp_test",
                "amount": 20000,
                "currency": "INR",
            }

        monkeypatch.setattr(views, "credentials_configured", lambda: True)
        monkeypatch.setattr(views, "create_order", fake_create_order)

        owner = make_provider_user(_next_name("shop"))
        profile = make_profile(owner)
        make_service(profile, price=40000, deposit_percent=50)

        customer = a_customer()
        starts_at = (timezone.localtime() + timedelta(days=3)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        booking = customer.client.post(
            f"{V1}/bookings/new/",
            {
                "provider": profile.pk,
                "services": [profile.services.first().pk],
                "starts_at": starts_at.isoformat(),
            },
            **customer.auth(),
        )
        assert booking.status_code == 201, booking.data

        key = str(uuid.uuid4())
        order_body = {"booking": booking.data["reference"]}
        first = customer.client.post(f"{V1}/payments/orders/", order_body, **customer.as_(key))
        second = customer.client.post(f"{V1}/payments/orders/", order_body, **customer.as_(key))

        assert first.status_code in (200, 201), first.data
        assert second.data["razorpay"]["order_id"] == first.data["razorpay"]["order_id"]
        assert second.data["payment"]["id"] == first.data["payment"]["id"]
