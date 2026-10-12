"""Finding the customers who liked the haircut and quietly stopped.

Cheapest revenue on the platform: the work is already done. Somebody liked
this shop enough to sit in the chair once, and then life happened.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from accounts.models import NotificationKey, NotificationPreference, RebookingNudge
from accounts.reengagement import lapsed_customers, send_nudges, wants_nudge
from bookings.models import Booking, BookingStatus
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


def _when(days_ago: float) -> datetime:
    return timezone.now() - timedelta(days=days_ago)


def a_visit(*, days_ago: float = 56, customer=None, provider=None):
    """A completed booking that finished ``days_ago``."""
    customer = customer or make_user(_next_name("customer"))
    if provider is None:
        provider = make_profile(
            make_provider_user(_next_name("shop")), display_name="Sharp Cuts Studio"
        )
    # One menu item per shop; a second visit at the same shop must not try to
    # add another with the same name.
    service = provider.services.filter(is_active=True).first() or make_service(
        provider, price=20000
    )
    ends_at = _when(days_ago)

    booking = Booking.objects.create(
        customer=customer,
        provider=provider,
        staff=None,
        starts_at=ends_at - timedelta(minutes=30),
        ends_at=ends_at,
        status=BookingStatus.COMPLETED,
        subtotal=service.price,
        platform_fee=0,
        total=service.price,
        deposit=0,
        balance=service.price,
        currency="INR",
    )
    return customer, provider, booking


def a_token(user) -> None:
    from accounts.models import PushToken

    PushToken.objects.create(user=user, token=f"ExponentPushToken[{user.pk}]", active=True)


class TestWhoIsLapsed:
    def test_seven_weeks_past_counts(self):
        a_visit(days_ago=56)
        assert len(lapsed_customers()) == 1

    def test_three_weeks_past_does_not(self):
        """Somebody mid-routine is not lapsed. Nudging them is nagging."""
        a_visit(days_ago=21)
        assert lapsed_customers() == []

    def test_yesterday_does_not(self):
        a_visit(days_ago=1)
        assert lapsed_customers() == []

    def test_five_months_does_not(self):
        """Past this they are gone, not lapsed, and a message unsettles."""
        a_visit(days_ago=200)
        assert lapsed_customers() == []

    def test_an_upcoming_booking_is_not_a_visit(self):
        _customer, _provider, booking = a_visit(days_ago=56)
        Booking.objects.filter(pk=booking.pk).update(status=BookingStatus.CONFIRMED)
        assert lapsed_customers() == []

    def test_a_cancelled_booking_is_not_a_visit(self):
        _customer, _provider, booking = a_visit(days_ago=56)
        Booking.objects.filter(pk=booking.pk).update(status=BookingStatus.CANCELLED_BY_CUSTOMER)
        assert lapsed_customers() == []

    def test_their_most_recent_visit_is_the_one_that_counts(self):
        customer, provider, _old = a_visit(days_ago=200)
        _new_customer, _new_provider, recent = a_visit(
            days_ago=20, customer=customer, provider=provider
        )
        assert lapsed_customers() == []
        assert recent.customer_id == customer.pk

    def test_one_row_per_customer_not_one_per_booking(self):
        customer, provider, _first = a_visit(days_ago=120)
        _second_c, _second_p, _second = a_visit(days_ago=60, customer=customer, provider=provider)

        candidates = lapsed_customers()

        assert len(candidates) == 1
        assert candidates[0].pair == (customer.pk, provider.pk)


class TestSending:
    def test_a_lapsed_customer_is_nudged_exactly_once(self):
        customer, provider, booking = a_visit(days_ago=56)
        a_token(customer)

        first = send_nudges()
        assert first["sent"] == 1

        # Run it again an hour later, and again tomorrow.
        second = send_nudges()
        assert second["sent"] == 0
        assert second["already_nudged"] == 1

        assert RebookingNudge.objects.filter(customer=customer, provider=provider).count() == 1
        assert booking.pk == RebookingNudge.objects.get().last_booking_id

    def test_the_record_survives_a_second_lapse(self):
        """The point of storing it: dates cannot tell these apart."""
        customer, provider, _first = a_visit(days_ago=56)
        a_token(customer)
        send_nudges()

        # They come back, then lapse again.
        a_visit(days_ago=10, customer=customer, provider=provider)
        _c, _p, later = a_visit(days_ago=60, customer=customer, provider=provider)

        assert send_nudges()["already_nudged"] == 1
        assert RebookingNudge.objects.get().last_booking_id != later.pk

    def test_the_message_links_to_the_shop(self):
        customer, provider, _booking = a_visit(days_ago=56)
        a_token(customer)

        sent = []
        import accounts.reengagement as module

        module.deliver_push = lambda tokens, **kw: sent.append(kw)
        send_nudges()

        assert len(sent) == 1
        assert provider.display_name in sent[0]["body"]
        assert f"/shops/{provider.slug}/" in sent[0]["data"]["url"]

    def test_somebody_with_no_device_is_counted_but_not_sent(self):
        _customer, _provider, _booking = a_visit(days_ago=56)

        counts = send_nudges()

        assert counts["no_tokens"] == 1
        assert counts["sent"] == 0
        assert not RebookingNudge.objects.exists()


class TestPreferences:
    def test_somebody_who_opted_out_of_offers_is_not_nudged(self):
        customer, _provider, _booking = a_visit(days_ago=56)
        a_token(customer)
        NotificationPreference.objects.create(
            user=customer, key=NotificationKey.OFFERS_AND_PROMOTIONS, enabled=False
        )
        NotificationPreference.objects.create(
            user=customer, key=NotificationKey.BOOKING_REMINDERS, enabled=False
        )

        counts = send_nudges()

        assert counts["opted_out"] == 1
        assert counts["sent"] == 0
        assert not RebookingNudge.objects.exists()

    def test_somebody_who_wants_reminders_still_hears(self):
        """They have not muted us; a nudge is not marketing."""
        customer, _provider, _booking = a_visit(days_ago=56)
        a_token(customer)

        assert wants_nudge(customer) is True
        assert send_nudges()["sent"] == 1

    def test_an_opt_out_is_read_from_where_the_settings_screen_writes(self):
        customer = make_user(_next_name("quiet"))
        client, token = logged_in(customer)
        make_profile(customer)

        client.put(
            f"{V1}/me/notification-preferences/",
            '{"preferences": {"offersAndPromotions": false, "bookingReminders": false}}',
            content_type="application/json",
            **auth_header(token),
        )

        assert wants_nudge(customer) is False

    def test_nobody_nudged_without_consent_is_recorded(self):
        """Otherwise opting out later would not stop a nudge already due."""
        customer, _provider, _booking = a_visit(days_ago=56)
        a_token(customer)
        NotificationPreference.objects.create(
            user=customer, key=NotificationKey.OFFERS_AND_PROMOTIONS, enabled=False
        )
        NotificationPreference.objects.create(
            user=customer, key=NotificationKey.BOOKING_REMINDERS, enabled=False
        )

        send_nudges()

        assert RebookingNudge.objects.count() == 0


class TestTheTask:
    def test_it_is_scheduled(self):
        from config.celery import app

        scheduled = {conf["task"] for conf in app.conf.beat_schedule.values()}
        assert "bookings.reminders.send_rebooking_nudges" in scheduled

    def test_it_runs(self, monkeypatch):
        from bookings import tasks

        sent = []
        monkeypatch.setattr(
            "accounts.reengagement.deliver_push", lambda tokens, **kw: sent.append(kw)
        )
        customer, _provider, _booking = a_visit(days_ago=56)
        a_token(customer)

        counts = tasks.send_rebooking_nudges()

        assert counts["sent"] == 1
        assert len(sent) == 1
