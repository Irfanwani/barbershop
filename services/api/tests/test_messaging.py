"""WhatsApp confirmations and replies.

The acceptance for this feature is three sentences, and two of them are about
not doing something twice:

- a booking sends one confirmation
- a webhook retry does not send a second
- a reply that says "cancel" cancels the booking

So the tests are weighted towards the repeats and the refusals. A confirmation
that arrives is easy; one that arrives four times is a customer who stops
reading them, and WhatsApp is charged per message.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from messaging import gateway, outbound
from messaging.models import (
    InboundReply,
    MessageKind,
    MessageStatus,
    ReplyIntent,
    WhatsAppMessage,
)
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
BOOKINGS = f"{V1}/bookings/"
WEBHOOK = f"{V1}/messaging/webhook/"

_counter = 0
sent: list[dict[str, Any]] = []


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


@pytest.fixture(autouse=True)
def a_whatsapp_provider(settings, monkeypatch):
    """A provider that always answers, and records what it was asked to send.

    Configured through settings rather than mocked at the call site, so the
    whole path - gateway, model, idempotency key - is what is under test.
    """
    settings.WHATSAPP_PROVIDER = "twilio"
    settings.WHATSAPP_ACCOUNT_SID = "AC-test"
    settings.WHATSAPP_AUTH_TOKEN = "token"
    settings.WHATSAPP_FROM = "+910000000000"
    settings.WHATSAPP_WEBHOOK_SECRET = "secret"

    sent.clear()

    def fake_send(*, to, body, idempotency_key):
        sent.append({"to": to, "body": body, "key": idempotency_key})
        return gateway.SendResult(ok=True, provider_message_id=f"SM{len(sent)}")

    # The provider handler, not ``gateway.send`` itself, so the "is anything
    # configured?" check inside send() still runs for real.
    monkeypatch.setattr(gateway, "_send_twilio", fake_send)


def a_booking(*, phone: str = "+919876543210", deposit_percent: int = 50):
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner, display_name="Sharp Cuts Studio")
    service = make_service(profile, price=20000, deposit_percent=deposit_percent)

    customer = make_user(_next_name("customer"))
    customer.phone = phone
    customer.save(update_fields=["phone"])

    client, token = logged_in(customer)
    starts_at = (timezone.localtime() + timedelta(days=3)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    response = client.post(
        f"{BOOKINGS}new/",
        {
            "provider": profile.pk,
            "services": [service.pk],
            "starts_at": starts_at.isoformat(),
        },
        **auth_header(token),
    )
    assert response.status_code == 201, response.data
    return Booking.objects.get(reference=response.data["reference"]), customer


def pay(booking: Booking) -> None:
    """Take the deposit, which is what triggers a confirmation."""
    import payments.views as views

    payment = Payment.objects.filter(booking=booking, kind="deposit").first()
    if payment is None:
        payment = Payment.objects.create(
            booking=booking,
            kind="deposit",
            amount=booking.deposit,
            currency=booking.currency,
            status=PaymentStatus.CREATED,
            razorpay_order_id=f"order_{uuid.uuid4().hex[:12]}",
        )
    views.capture(payment, f"pay_{uuid.uuid4().hex[:8]}", "sig")


class TestOneConfirmation:
    def test_a_paid_booking_sends_one(self):
        booking, _customer = a_booking()

        pay(booking)

        assert len(sent) == 1
        assert WhatsAppMessage.objects.filter(booking=booking).count() == 1

    def test_capturing_twice_does_not_send_twice(self):
        """A webhook redelivery is the normal way a capture happens twice."""
        booking, _customer = a_booking()

        pay(booking)
        pay(booking)

        assert len(sent) == 1, "the customer got the same confirmation twice"

    def test_the_key_is_about_the_booking_not_the_attempt(self):
        booking, _customer = a_booking()

        pay(booking)

        assert sent[0]["key"] == outbound.confirmation_key(booking.reference)

    def test_an_unpaid_booking_is_not_confirmed(self):
        """It exists, but it is not secured. Saying "you're booked" here is a
        thing the customer will hold us to."""
        booking, _customer = a_booking()

        assert not sent
        assert booking.status == BookingStatus.PENDING_PAYMENT

    def test_a_reminder_is_a_different_message(self):
        """Otherwise the reminder collides with the confirmation's key and
        silently never goes out."""
        booking, _customer = a_booking()
        pay(booking)

        outbound.send_reminder(booking)

        assert len(sent) == 2
        assert {message.kind for message in WhatsAppMessage.objects.all()} == {
            MessageKind.BOOKING_CONFIRM,
            MessageKind.BOOKING_REMINDER,
        }

    def test_nobody_with_no_number_is_messaged(self):
        booking, _customer = a_booking(phone="")

        pay(booking)

        assert not sent
        assert not WhatsAppMessage.objects.exists()


class TestRetrying:
    def test_a_message_the_gateway_dropped_is_sent_again(self):
        """The timeout case: we sent it, the gateway never answered, and the
        customer is unconfirmed until the shop tells them otherwise."""
        booking, _customer = a_booking()
        pay(booking)

        # Pretend the send timed out rather than succeeded.
        message = WhatsAppMessage.objects.get(booking=booking)
        message.status = MessageStatus.FAILED
        message.failure_reason = "timed out"
        message.save(update_fields=["status", "failure_reason"])

        sent.clear()
        assert outbound.retry_queued(older_than_minutes=0) == 1

        assert len(sent) == 1

    def test_a_delivered_message_is_never_re_sent(self):
        """It cost money and the customer already has it."""
        booking, _customer = a_booking()
        pay(booking)
        sent.clear()

        assert outbound.retry_queued(older_than_minutes=0) == 0
        assert not sent

    def test_a_retry_cannot_produce_a_second_row(self):
        booking, _customer = a_booking()
        pay(booking)
        message = WhatsAppMessage.objects.get(booking=booking)
        message.status = MessageStatus.FAILED
        message.save(update_fields=["status"])

        outbound.retry_queued(older_than_minutes=0)

        assert WhatsAppMessage.objects.filter(booking=booking).count() == 1


def sign(body: bytes) -> str:
    return hmac.new(b"secret", body, hashlib.sha256).hexdigest()


def post_webhook(payload: dict, *, signature: str | None = None):
    client, _token = logged_in(make_user(_next_name("someone")))
    raw = json.dumps(payload).encode()
    return client.post(
        WEBHOOK,
        raw,
        content_type="application/json",
        **{
            "HTTP_AUTHORIZATION": "",
            "HTTP_X_WHATSAPP_SIGNATURE": signature if signature is not None else sign(raw),
        },
    )


class TestTheWebhookIsGenuine:
    def test_a_forged_callback_does_nothing(self):
        booking, _customer = a_booking()
        pay(booking)

        response = post_webhook(
            {
                "MessageSid": "SM1",
                "MessageStatus": "delivered",
            },
            signature="not-the-signature",
        )

        assert response.status_code == 403
        assert WhatsAppMessage.objects.get(booking=booking).status == MessageStatus.SENT

    def test_it_is_accepted_with_a_good_one(self):
        booking, _customer = a_booking()
        pay(booking)

        response = post_webhook({"MessageSid": "SM1", "MessageStatus": "delivered"})

        assert response.status_code == 200
        assert WhatsAppMessage.objects.get(booking=booking).status == MessageStatus.DELIVERED

    def test_an_ignored_event_is_still_acknowledged(self):
        """A non-2xx makes the provider redeliver forever, including for events
        we deliberately do not handle."""
        client, _token = logged_in(make_user(_next_name("n")))
        raw = json.dumps({"something": "unfamiliar"}).encode()

        response = client.post(
            WEBHOOK,
            raw,
            content_type="application/json",
            HTTP_X_WHATSAPP_SIGNATURE=sign(raw),
        )

        assert response.status_code == 200


class TestDeliveryStatus:
    def test_it_lands_on_the_right_message(self):
        booking, _customer = a_booking()
        pay(booking)

        post_webhook({"MessageSid": "SM1", "MessageStatus": "delivered"})
        post_webhook({"MessageSid": "SM1", "MessageStatus": "read"})

        message = WhatsAppMessage.objects.get(booking=booking)
        assert message.status == MessageStatus.READ
        assert message.delivered_at is not None

    def test_a_redelivered_status_changes_nothing(self):
        booking, _customer = a_booking()
        pay(booking)

        for _ in range(3):
            post_webhook({"MessageSid": "SM1", "MessageStatus": "delivered"})

        assert WhatsAppMessage.objects.get(booking=booking).status == MessageStatus.DELIVERED

    def test_a_late_sent_cannot_undo_a_delivery(self):
        """Providers send these out of order. A late "sent" must not make a
        delivered confirmation look undelivered, because that is how a
        dashboard ends up reporting 0% delivery for messages that arrived."""
        booking, _customer = a_booking()
        pay(booking)
        post_webhook({"MessageSid": "SM1", "MessageStatus": "delivered"})

        post_webhook({"MessageSid": "SM1", "MessageStatus": "sent"})

        assert WhatsAppMessage.objects.get(booking=booking).status == MessageStatus.DELIVERED

    def test_a_status_for_a_message_we_never_sent_is_ignored(self):
        _client, _token = logged_in(make_user(_next_name("n")))

        response = post_webhook({"MessageSid": "SM-nope", "MessageStatus": "delivered"})

        assert response.status_code == 200
        assert not WhatsAppMessage.objects.exists()


class TestRepliesCancelTheBooking:
    def test_cancel_cancels_it(self):
        booking, _customer = a_booking()
        pay(booking)

        post_webhook(
            {
                "MessageSid": "SM-reply-1",
                "From": "+919876543210",
                "Body": "cancel",
            }
        )

        booking.refresh_from_db()
        assert booking.status == BookingStatus.CANCELLED_BY_CUSTOMER

    @pytest.mark.parametrize(
        "body",
        [
            "cancel",
            "CANCEL",
            "Please cancel",
            "pls cancel my booking",
            "I can't make it",
            "won't be able to come",
            "no longer coming",
        ],
    )
    def test_it_reads_cancel_how_a_person_says_it(self, body):
        """Only one of these is on any list anybody writes, and all of them
        arrive."""
        booking, _customer = a_booking()
        pay(booking)

        post_webhook(
            {"MessageSid": f"SM-{uuid.uuid4().hex[:8]}", "From": "+919876543210", "Body": body}
        )

        booking.refresh_from_db()
        assert booking.status == BookingStatus.CANCELLED_BY_CUSTOMER

    def test_a_redelivered_reply_does_not_cancel_twice(self):
        """The provider sends every webhook more than once. Two cancellations
        is two different fee calculations."""
        booking, _customer = a_booking()
        pay(booking)

        payload = {
            "MessageSid": "SM-reply-once",
            "From": "+919876543210",
            "Body": "cancel",
        }
        post_webhook(payload)
        post_webhook(payload)
        post_webhook(payload)

        assert InboundReply.objects.count() == 1

    def test_yes_does_not_cancel_it(self):
        booking, _customer = a_booking()
        pay(booking)

        post_webhook({"MessageSid": "SM-yes", "From": "+919876543210", "Body": "yes please"})

        booking.refresh_from_db()
        assert booking.status != BookingStatus.CANCELLED_BY_CUSTOMER
        assert InboundReply.objects.get().intent == ReplyIntent.CONFIRM

    def test_reschedule_is_left_to_a_person(self):
        """A reschedule needs a new time, and nobody who typed the word has
        said which one."""
        booking, _customer = a_booking()
        pay(booking)

        post_webhook(
            {
                "MessageSid": "SM-resched",
                "From": "+919876543210",
                "Body": "can we reschedule?",
            }
        )

        booking.refresh_from_db()
        assert booking.status != BookingStatus.CANCELLED_BY_CUSTOMER
        assert "needs a time" in InboundReply.objects.get().handled_note

    def test_a_reply_from_somebody_else_does_nothing(self):
        booking, _customer = a_booking()
        pay(booking)

        post_webhook({"MessageSid": "SM-stranger", "From": "+919000000000", "Body": "cancel"})

        booking.refresh_from_db()
        assert booking.status != BookingStatus.CANCELLED_BY_CUSTOMER

    def test_thanks_to_a_cancellation_is_not_a_cancellation(self):
        """Cancelling somebody because they said thank you is the worst
        version of this bug."""
        booking, _customer = a_booking()
        pay(booking)

        reply = outbound.record_reply(
            sender="+919876543210", body="thanks", provider_message_id="SM-thanks"
        )

        booking.refresh_from_db()
        assert booking.status != BookingStatus.CANCELLED_BY_CUSTOMER
        assert reply.intent == ReplyIntent.NONE

    def test_the_reply_is_kept_even_when_it_makes_no_sense(self):
        """A reply the app cannot parse is still a reply from a customer.
        Discarding it means the next person to look has no idea anybody tried."""
        _booking, _customer = a_booking()

        outbound.record_reply(
            sender="+919876543210", body="asdfgh", provider_message_id="SM-nonsense"
        )

        reply = InboundReply.objects.get()
        assert reply.body == "asdfgh"
        assert reply.handled_at is not None


class TestWhenThereIsNoProvider:
    def test_the_booking_still_happens(self, settings, monkeypatch):
        settings.WHATSAPP_PROVIDER = ""
        booking, _customer = a_booking()

        pay(booking)

        booking.refresh_from_db()
        assert booking.status in (
            BookingStatus.CONFIRMED,
            BookingStatus.AWAITING_CONFIRMATION,
        )

    def test_nothing_is_sent(self, settings, monkeypatch):
        settings.WHATSAPP_PROVIDER = ""
        booking, _customer = a_booking()

        pay(booking)

        assert not sent


class TestTheMessageItself:
    def test_it_names_the_shop_and_the_time(self):
        booking, _customer = a_booking()
        pay(booking)

        body = sent[0]["body"]
        assert "Sharp Cuts Studio" in body
        assert "10:00" in body or "10:00 AM" in body

    def test_it_says_how_to_change_it(self):
        booking, _customer = a_booking()
        pay(booking)

        assert booking.reference in sent[0]["body"]

    def test_the_time_is_the_shops_clock_not_utc(self):
        """A Bengaluru shop saying "10:00" means 10:00 there. UTC would be
        half past five in the afternoon, which is a different appointment."""
        booking, _customer = a_booking()
        booking.provider.timezone_name = "Asia/Kolkata"
        booking.provider.save(update_fields=["timezone_name"])
        pay(booking)

        assert "AM" in sent[0]["body"] or "PM" in sent[0]["body"]

    def test_a_number_is_dialled_in_full(self):
        booking, _customer = a_booking(phone="9876543210")

        pay(booking)

        assert sent[0]["to"] == "919876543210"
