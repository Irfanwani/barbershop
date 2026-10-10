"""Tests for ``/api/v1/payments/``.

These exist mainly because of what they refuse to do. The old API let any
authenticated user mark any booking paid; each of those holes gets a test that
says so.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from django.conf import settings
from django.urls import reverse

from bookings.models import BookingStatus
from payments.models import Payment, PaymentStatus
from tests.factories import auth_header, logged_in, make_booking, make_user

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
PAYMENTS = f"{V1}/payments/"


def sign(body: bytes, secret: str | None = None) -> str:
    secret = secret or settings.RAZORPAY_WEBHOOK_SECRET
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def webhook_payload(order_id: str, status: str = "captured", payment_id: str = "pay_123") -> dict:
    return {
        "event": f"payment.{status}",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "status": status,
                    "amount": 27500,
                }
            }
        },
    }


@pytest.fixture
def payable_booking():
    """A confirmed-provider booking awaiting payment."""
    booking = make_booking(status=BookingStatus.PENDING_PAYMENT)
    return booking


# ---------------------------------------------------------------------------
# Creating an order
# ---------------------------------------------------------------------------


class TestCreateOrder:
    def _post(self, client, token, booking):
        return client.post(
            PAYMENTS + "orders/",
            {"booking": booking.reference},
            content_type="application/json",
            **auth_header(token),
        )

    def test_creates_an_order_for_the_bookings_total(self, payable_booking, monkeypatch):
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

        client, token = logged_in(payable_booking.customer)
        response = self._post(client, token, payable_booking)

        assert response.status_code == 201, response.content
        body = response.json()
        assert body["razorpay"]["order_id"] == "order_abc"
        assert body["payment"]["amount"] == payable_booking.total
        assert Payment.objects.count() == 1

    def test_the_amount_cannot_be_chosen_by_the_client(self, payable_booking, monkeypatch):
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
            },
        )

        client, token = logged_in(payable_booking.customer)
        response = client.post(
            PAYMENTS + "orders/",
            {"booking": payable_booking.reference, "amount": 1},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 201
        assert response.json()["payment"]["amount"] == payable_booking.total

    def test_cannot_pay_for_someone_elses_booking(self, payable_booking, monkeypatch):
        from payments import views

        monkeypatch.setattr(views, "credentials_configured", lambda: True)
        client, token = logged_in(make_user())

        response = self._post(client, token, payable_booking)

        assert response.status_code == 400
        assert Payment.objects.count() == 0

    def test_cannot_pay_twice(self, payable_booking, monkeypatch):
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
            },
        )
        client, token = logged_in(payable_booking.customer)
        self._post(client, token, payable_booking)
        Payment.objects.update(status=PaymentStatus.CAPTURED)

        second = self._post(client, token, payable_booking)

        assert second.status_code == 400

    def test_a_confirmed_booking_needs_no_payment(self, monkeypatch):
        from payments import views

        monkeypatch.setattr(views, "credentials_configured", lambda: True)
        booking = make_booking(status=BookingStatus.CONFIRMED)
        client, token = logged_in(booking.customer)

        assert self._post(client, token, booking).status_code == 400

    def test_unconfigured_server_says_so_plainly(self, payable_booking, monkeypatch):
        from payments import views

        monkeypatch.setattr(views, "credentials_configured", lambda: False)
        client, token = logged_in(payable_booking.customer)

        response = self._post(client, token, payable_booking)

        assert response.status_code == 400
        assert "not configured" in response.json()["error"]["message"]


# ---------------------------------------------------------------------------
# The webhook — the only thing that may mark a booking paid
# ---------------------------------------------------------------------------


class TestWebhook:
    def _send(self, client, payload: dict, signature: str | None = None):
        body = json.dumps(payload).encode()
        return client.post(
            PAYMENTS + "webhook/",
            data=body,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=signature if signature is not None else sign(body),
        )

    def test_capture_marks_the_payment_and_confirms_the_booking(self, payable_booking):
        payment = Payment.objects.create(
            booking=payable_booking,
            razorpay_order_id="order_abc",
            amount=payable_booking.total,
        )
        from django.test import Client

        response = self._send(Client(), webhook_payload("order_abc"))

        assert response.status_code == 200
        payment.refresh_from_db()
        payable_booking.refresh_from_db()
        assert payment.status == PaymentStatus.CAPTURED
        assert payment.captured_at is not None
        assert payable_booking.status == BookingStatus.CONFIRMED

    def test_approval_required_providers_wait_for_confirmation(self):
        booking = make_booking(status=BookingStatus.PENDING_PAYMENT)
        booking.provider.requires_approval = True
        booking.provider.save()
        Payment.objects.create(booking=booking, razorpay_order_id="order_x", amount=booking.total)
        from django.test import Client

        self._send(Client(), webhook_payload("order_x"))
        booking.refresh_from_db()

        assert booking.status == BookingStatus.AWAITING_CONFIRMATION

    def test_a_forged_signature_is_refused(self, payable_booking):
        """The whole security model: HMAC over the raw body, or nothing."""
        Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )
        from django.test import Client

        response = self._send(Client(), webhook_payload("order_abc"), signature="a" * 64)

        assert response.status_code == 400
        payable_booking.refresh_from_db()
        assert payable_booking.status == BookingStatus.PENDING_PAYMENT

    def test_a_tampered_body_is_refused(self, payable_booking):
        """Sign one body, send another."""
        from django.test import Client

        Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )
        signature = sign(json.dumps(webhook_payload("order_other")).encode())

        response = self._send(Client(), webhook_payload("order_abc"), signature=signature)

        assert response.status_code == 400

    def test_a_missing_signature_is_refused(self, payable_booking):
        from django.test import Client

        Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )

        response = self._send(Client(), webhook_payload("order_abc"), signature="")

        assert response.status_code == 400

    def test_another_secret_does_not_work(self, payable_booking):
        from django.test import Client

        Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )

        response = self._send(
            Client(), webhook_payload("order_abc"), signature=sign(b"{}", "not-the-secret")
        )

        assert response.status_code == 400

    def test_is_idempotent(self, payable_booking):
        """Razorpay retries. A second capture must not double-count."""
        Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )
        from django.test import Client

        client = Client()
        self._send(client, webhook_payload("order_abc"))
        first = Payment.objects.get().captured_at
        self._send(client, webhook_payload("order_abc"))

        assert Payment.objects.get().captured_at == first

    def test_a_failure_marks_the_payment_failed(self, payable_booking):
        payment = Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )
        from django.test import Client

        self._send(Client(), webhook_payload("order_abc", status="failed"))

        payment.refresh_from_db()
        payable_booking.refresh_from_db()
        assert payment.status == PaymentStatus.FAILED
        assert payable_booking.status == BookingStatus.PENDING_PAYMENT

    def test_an_unrelated_event_is_acknowledged_not_retried(self):
        from django.test import Client

        response = self._send(Client(), {"event": "subscription.charged", "payload": {}})

        assert response.status_code == 200
        assert response.json()["handled"] is False

    def test_an_unknown_order_is_acknowledged(self):
        from django.test import Client

        response = self._send(Client(), webhook_payload("order_does_not_exist"))

        assert response.status_code == 200
        assert response.json()["handled"] is False

    def test_does_not_require_a_token(self):
        """Razorpay has no account here; the signature is the credential."""
        from django.test import Client

        response = Client().post(PAYMENTS + "webhook/", data=b"{}", content_type="application/json")

        assert response.status_code == 400, "bad signature, not 401"


# ---------------------------------------------------------------------------
# Client-side verification
# ---------------------------------------------------------------------------


class TestVerify:
    def _post(self, client, token, signature: str = "sig"):
        return client.post(
            PAYMENTS + "verify/",
            {
                "razorpay_order_id": "order_abc",
                "razorpay_payment_id": "pay_123",
                "razorpay_signature": signature,
            },
            content_type="application/json",
            **auth_header(token),
        )

    def test_a_bad_signature_does_not_capture(self, payable_booking, monkeypatch):
        from payments import views

        monkeypatch.setattr(views, "verify_payment_signature", lambda *a: False)
        Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )
        client, token = logged_in(payable_booking.customer)

        response = self._post(client, token)

        assert response.status_code == 400
        assert Payment.objects.get().status != PaymentStatus.CAPTURED

    def test_a_valid_signature_but_a_failed_payment_is_not_captured(
        self, payable_booking, monkeypatch
    ):
        from payments import views

        monkeypatch.setattr(views, "verify_payment_signature", lambda *a: True)
        monkeypatch.setattr(views, "fetch_payment", lambda pid: {"status": "failed"})
        Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )
        client, token = logged_in(payable_booking.customer)

        response = self._post(client, token)

        assert response.status_code == 400
        assert Payment.objects.get().status == PaymentStatus.FAILED

    def test_a_verified_capture_confirms_the_booking(self, payable_booking, monkeypatch):
        from payments import views

        monkeypatch.setattr(views, "verify_payment_signature", lambda *a: True)
        monkeypatch.setattr(views, "fetch_payment", lambda pid: {"status": "captured"})
        Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )
        client, token = logged_in(payable_booking.customer)

        response = self._post(client, token)

        assert response.status_code == 200
        payable_booking.refresh_from_db()
        assert payable_booking.status == BookingStatus.CONFIRMED

    def test_cannot_verify_someone_elses_payment(self, payable_booking, monkeypatch):
        from payments import views

        monkeypatch.setattr(views, "verify_payment_signature", lambda *a: True)
        Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )
        client, token = logged_in(make_user())

        assert self._post(client, token).status_code == 400


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


class TestDetail:
    def test_the_customer_can_read_their_payment(self, payable_booking):
        payment = Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )
        client, token = logged_in(payable_booking.customer)

        response = client.get(f"{PAYMENTS}{payment.razorpay_order_id}/", **auth_header(token))

        assert response.status_code == 200
        assert response.json()["booking_reference"] == payable_booking.reference

    def test_a_stranger_cannot(self, payable_booking):
        Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )
        client, token = logged_in(make_user())

        assert client.get(f"{PAYMENTS}order_abc/", **auth_header(token)).status_code == 404

    def test_the_provider_can_read_it(self, payable_booking):
        Payment.objects.create(
            booking=payable_booking, razorpay_order_id="order_abc", amount=payable_booking.total
        )
        client, token = logged_in(payable_booking.provider.user)

        assert client.get(f"{PAYMENTS}order_abc/", **auth_header(token)).status_code == 200


# ---------------------------------------------------------------------------
# Signature helpers
# ---------------------------------------------------------------------------


class TestSignatureHelpers:
    def test_webhook_signature_accepts_the_right_body(self):
        from payments.services import verify_webhook_signature

        body = b'{"event":"payment.captured"}'
        assert verify_webhook_signature(body, sign(body))

    def test_webhook_signature_rejects_a_tampered_body(self):
        from payments.services import verify_webhook_signature

        body = b'{"event":"payment.captured"}'
        assert not verify_webhook_signature(b'{"event":"payment.failed"}', sign(body))

    def test_payment_signature_follows_razorpays_scheme(self):
        from payments.services import verify_payment_signature

        expected = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(),
            b"order_abc|pay_123",
            hashlib.sha256,
        ).hexdigest()

        assert verify_payment_signature("order_abc", "pay_123", expected)

    def test_payment_signature_rejects_a_swap(self):
        from payments.services import verify_payment_signature

        expected = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(), b"order_abc|pay_123", hashlib.sha256
        ).hexdigest()

        assert not verify_payment_signature("order_other", "pay_123", expected)

    def test_no_secret_means_no_signature_is_good(self):
        from payments.services import verify_webhook_signature

        assert not verify_webhook_signature(b"{}", "anything")


def test_webhook_url_is_reverseable():
    assert reverse("v1:payments:webhook") == "/api/v1/payments/webhook/"
