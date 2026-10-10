"""Scheduled work: booking reminders, expiry and account housekeeping.

These are the jobs that were previously nobody's job. The tests here are
deliberately about *not sending the wrong thing*: a reminder that repeats every
fifteen minutes, or one sent to someone who turned them off, is worse than no
reminder at all.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus, slot_grid
from bookings.tasks import (
    EXPIRY_GRACE,
    expire_stale_bookings,
    send_daily_reminders,
    send_evening_reminders,
)
from core import notifications
from core.notifications import deliver_push
from tests import factories

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def captured_push(monkeypatch):
    """Record what would have been pushed, without pushing anything."""
    sent: list[dict] = []

    def _capture(tokens, *, title, body, data=None):
        sent.append({"tokens": list(tokens), "title": title, "body": body, "data": data})
        return True

    monkeypatch.setattr(notifications, "deliver_push", _capture)
    # The tasks import the symbol directly, so patch it there too.
    import bookings.tasks as tasks_module

    monkeypatch.setattr(tasks_module, "deliver_push", _capture)
    return sent


def _booked_in(*, hours_from_now: int, status=BookingStatus.CONFIRMED, **kwargs) -> Booking:
    starts_at = timezone.now() + timedelta(hours=hours_from_now)
    return factories.make_booking(
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        status=status,
        **kwargs,
    )


def _with_token(user, token: str = "ExponentPushToken[test]"):
    return user.push_tokens.create(token=token, platform="android")


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------


class TestDailyReminders:
    def test_reaches_both_sides_about_an_appointment_today(self, captured_push):
        booking = _booked_in(hours_from_now=2.5)
        _with_token(booking.customer)
        _with_token(booking.provider.user, "ExponentPushToken[shop]")

        result = send_daily_reminders()

        assert result == {"customer": 1, "provider": 1}
        assert len(captured_push) == 2

    def test_tells_each_side_something_different(self, captured_push):
        # The customer needs to know where to go; the provider needs to know
        # who is coming. The same sentence to both helps nobody.
        booking = _booked_in(hours_from_now=2.5)
        _with_token(booking.customer)
        _with_token(booking.provider.user, "ExponentPushToken[shop]")

        send_daily_reminders()

        bodies = {push["body"] for push in captured_push}
        assert len(bodies) == 2

    def test_does_not_repeat_itself_every_fifteen_minutes(self, captured_push):
        booking = _booked_in(hours_from_now=2.5)
        _with_token(booking.customer)
        _with_token(booking.provider.user, "ExponentPushToken[shop]")

        send_daily_reminders()
        captured_push.clear()
        send_daily_reminders()

        assert captured_push == []

    def test_says_nothing_about_an_appointment_that_is_not_today(self, captured_push):
        _booked_in(hours_from_now=50)
        assert send_daily_reminders() == {"customer": 0, "provider": 0}
        assert captured_push == []

    def test_does_not_remind_about_an_unaccepted_request(self, captured_push):
        # Reminding someone about a slot the provider has not agreed to is
        # worse than saying nothing.
        booking = _booked_in(hours_from_now=2, status=BookingStatus.AWAITING_CONFIRMATION)
        _with_token(booking.customer)
        _with_token(booking.provider.user, "ExponentPushToken[shop]")

        send_daily_reminders()

        assert captured_push == []

    def test_says_nothing_to_a_user_who_switched_reminders_off(self, captured_push):
        booking = _booked_in(hours_from_now=2.5)
        _with_token(booking.customer)
        _with_token(booking.provider.user, "ExponentPushToken[shop]")

        from accounts.models import CustomerProfile

        CustomerProfile.objects.create(user=booking.customer, reminders_enabled=False)

        result = send_daily_reminders()

        assert result == {"customer": 0, "provider": 1}

    def test_a_user_without_push_is_not_picked_up_again(self, captured_push):
        # Marked as reminded even though nothing was sent, or the job would
        # select this booking on every run forever.
        _booked_in(hours_from_now=2.5)

        send_daily_reminders()

        assert Booking.objects.filter(reminder_sent_at__isnull=False).count() == 1

    def test_the_reminder_points_at_the_booking(self, captured_push):
        booking = _booked_in(hours_from_now=2.5)
        _with_token(booking.customer)

        send_daily_reminders()

        assert captured_push[0]["data"]["reference"] == booking.reference


class TestEveningReminders:
    def test_reaches_both_sides_about_tomorrow(self, captured_push):
        booking = _booked_in(hours_from_now=13.5)
        _with_token(booking.customer)
        _with_token(booking.provider.user, "ExponentPushToken[shop]")

        assert send_evening_reminders() == {"customer": 1, "provider": 1}

    def test_does_not_double_up_with_the_morning_reminder(self, captured_push):
        booking = _booked_in(hours_from_now=13.5)
        _with_token(booking.customer)
        _with_token(booking.provider.user, "ExponentPushToken[shop]")

        send_evening_reminders()
        captured_push.clear()
        send_daily_reminders()

        # 13 hours out is inside the evening window, not the morning one.
        assert captured_push == []


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------


class TestExpiry:
    def test_a_confirmed_appointment_that_ended_becomes_a_no_show(self):
        booking = _booked_in(hours_from_now=-5)
        booking.ends_at = timezone.now() - timedelta(hours=5)
        booking.starts_at = booking.ends_at - timedelta(minutes=30)
        booking.save()

        counts = expire_stale_bookings()

        booking.refresh_from_db()
        assert counts["no_show"] == 1
        assert booking.status == BookingStatus.NO_SHOW
        assert booking.expired_at is not None

    def test_one_that_ended_recently_is_left_alone(self):
        # A haircut that ran ten minutes late is still happening.
        booking = _booked_in(hours_from_now=-1)
        booking.ends_at = timezone.now() - timedelta(minutes=10)
        booking.starts_at = booking.ends_at - timedelta(minutes=30)
        booking.save()

        expire_stale_bookings()

        booking.refresh_from_db()
        assert booking.status == BookingStatus.CONFIRMED

    def test_the_grace_period_is_a_real_grace_period(self):
        booking = _booked_in(hours_from_now=0)
        booking.ends_at = timezone.now() - EXPIRY_GRACE + timedelta(minutes=5)
        booking.starts_at = booking.ends_at - timedelta(minutes=30)
        booking.save()

        expire_stale_bookings()

        booking.refresh_from_db()
        assert booking.status == BookingStatus.CONFIRMED

    def test_an_unpaid_appointment_expires_without_blaming_anyone(self):
        booking = _booked_in(hours_from_now=-1, status=BookingStatus.PENDING_PAYMENT)

        expire_stale_bookings()

        booking.refresh_from_db()
        assert booking.status == BookingStatus.EXPIRED

    def test_an_unanswered_request_expires(self):
        booking = _booked_in(hours_from_now=-1, status=BookingStatus.AWAITING_CONFIRMATION)

        expire_stale_bookings()

        booking.refresh_from_db()
        assert booking.status == BookingStatus.EXPIRED

    def test_a_cancelled_appointment_is_left_alone(self):
        booking = _booked_in(hours_from_now=-5, status=BookingStatus.CANCELLED_BY_CUSTOMER)
        booking.ends_at = timezone.now() - timedelta(hours=5)
        booking.starts_at = booking.ends_at - timedelta(minutes=30)
        booking.save()

        expire_stale_bookings()

        booking.refresh_from_db()
        assert booking.status == BookingStatus.CANCELLED_BY_CUSTOMER

    def test_a_completed_appointment_is_left_alone(self):
        booking = _booked_in(hours_from_now=-5, status=BookingStatus.COMPLETED)
        booking.ends_at = timezone.now() - timedelta(hours=5)
        booking.starts_at = booking.ends_at - timedelta(minutes=30)
        booking.save()

        expire_stale_bookings()

        booking.refresh_from_db()
        assert booking.status == BookingStatus.COMPLETED

    def test_expiry_frees_the_slot_for_someone_else(self):
        """The whole point: a stale booking used to block that time forever."""
        provider = factories.make_profile()
        starts_at = timezone.now() - timedelta(hours=5)
        stale = factories.make_booking(
            provider=provider, starts_at=starts_at, ends_at=starts_at + timedelta(minutes=30)
        )

        expire_stale_bookings()
        stale.refresh_from_db()

        assert stale.status == BookingStatus.NO_SHOW
        assert (
            Booking.objects.filter(
                provider=provider, status__in=[BookingStatus.NO_SHOW, BookingStatus.EXPIRED]
            ).count()
            == 1
        )

    def test_future_appointments_are_untouched(self):
        booking = _booked_in(hours_from_now=5)

        expire_stale_bookings()

        booking.refresh_from_db()
        assert booking.status == BookingStatus.CONFIRMED


# ---------------------------------------------------------------------------
# Open/closed hours
# ---------------------------------------------------------------------------


class TestWorkingHours:
    def test_a_closed_day_offers_no_slots(self):
        from providers.models import WorkingHours

        provider = factories.make_profile()
        # Every day closed.
        for weekday in range(7):
            WorkingHours.objects.create(provider=provider, weekday=weekday, is_closed=True)

        assert slot_grid(provider, days=14) == []

    def test_opening_a_day_puts_its_slots_back(self):
        from datetime import time

        from providers.models import WorkingHours

        provider = factories.make_profile()
        for weekday in range(7):
            WorkingHours.objects.create(provider=provider, weekday=weekday, is_closed=True)

        target = timezone.localtime(timezone.now() + timedelta(days=1)).weekday()
        WorkingHours.objects.filter(provider=provider, weekday=target).update(
            is_closed=False, opens_at=time(9, 0), closes_at=time(20, 0)
        )

        assert slot_grid(provider, days=14), "an open weekday should offer slots"

    def test_closing_one_day_does_not_close_the_whole_week(self):
        from providers.models import WorkingHours

        provider = factories.make_profile()
        target = timezone.localtime(timezone.now() + timedelta(days=1)).weekday()
        WorkingHours.objects.create(provider=provider, weekday=target, is_closed=True)

        assert len(slot_grid(provider, days=14)) > 0

    def test_no_rows_falls_back_to_the_shops_own_hours(self):
        provider = factories.make_profile()
        # Sunday is treated as closed by default; every other day is open.
        assert provider.is_open_on(0) is True
        assert provider.is_open_on(6) is False

    def test_sunday_is_not_closed_when_the_shop_says_otherwise(self):
        from providers.models import WorkingHours

        provider = factories.make_profile()
        WorkingHours.objects.create(provider=provider, weekday=6, is_closed=False)

        assert provider.is_open_on(6) is True

    def test_a_shift_cannot_end_before_it_starts(self):
        from datetime import time

        from django.db.utils import IntegrityError

        from providers.models import WorkingHours

        provider = factories.make_profile()
        with pytest.raises(IntegrityError):
            WorkingHours.objects.create(
                provider=provider, weekday=0, opens_at=time(20, 0), closes_at=time(9, 0)
            )


# ---------------------------------------------------------------------------
# The push helper itself
# ---------------------------------------------------------------------------


class TestDeliverPush:
    def test_does_nothing_without_configured_push(self, settings, monkeypatch):
        settings.PUSH_NOTIFICATION_URL = ""
        calls: list = []
        monkeypatch.setattr(notifications.requests, "post", lambda *a, **k: calls.append(a))

        assert deliver_push(["ExponentPushToken[x]"], title="Hi", body="There") is False
        assert calls == []

    def test_returns_false_with_no_tokens(self):
        assert deliver_push([], title="Hi", body="There") is False

    def test_survives_an_outage(self, settings, monkeypatch):
        settings.PUSH_NOTIFICATION_URL = "https://example.test/push"

        def boom(*args, **kwargs):
            raise ConnectionError("push service down")

        monkeypatch.setattr(notifications.requests, "post", boom)

        # Must not raise: a push failure must never take down a booking.
        assert deliver_push(["ExponentPushToken[x]"], title="Hi", body="There") is False

    def test_deduplicates_devices(self, settings, monkeypatch):
        settings.PUSH_NOTIFICATION_URL = "https://example.test/push"
        seen: list[list[str]] = []

        def capture(url, json=None, timeout=None):
            seen.append(json["to"])
            return type("R", (), {"raise_for_status": lambda self: None})()

        monkeypatch.setattr(notifications.requests, "post", capture)

        deliver_push(
            ["ExponentPushToken[a]", "ExponentPushToken[a]", "ExponentPushToken[b]"],
            title="Hi",
            body="There",
        )

        assert seen == [["ExponentPushToken[a]", "ExponentPushToken[b]"]]

    def test_chunks_a_very_large_fan_out(self, settings, monkeypatch):
        settings.PUSH_NOTIFICATION_URL = "https://example.test/push"
        sizes: list[int] = []

        def capture(url, json=None, timeout=None):
            sizes.append(len(json["to"]))
            return type("R", (), {"raise_for_status": lambda self: None})()

        monkeypatch.setattr(notifications.requests, "post", capture)

        deliver_push(
            [f"ExponentPushToken[{i}]" for i in range(250)],
            title="Hi",
            body="There",
        )

        # Expo rejects an oversized batch outright rather than truncating it.
        assert sizes == [100, 100, 50]


# ---------------------------------------------------------------------------
# The schedule itself
# ---------------------------------------------------------------------------


class TestSchedule:
    """A scheduled task that does not exist fails only when beat fires.

    That is in production, nightly, with nobody watching. Cheap to check here.
    """

    def test_every_scheduled_task_is_importable(self):
        from config.celery import app

        app.loader.import_default_modules()
        scheduled = {conf["task"] for conf in app.conf.beat_schedule.values()}

        assert scheduled
        assert not scheduled - set(app.tasks)

    def test_reminders_are_not_scheduled_more_than_once_a_day(self):
        from config.celery import app

        reminder_jobs = [
            conf for name, conf in app.conf.beat_schedule.items() if "reminder" in name
        ]

        assert len(reminder_jobs) == 2

    def test_the_celery_broker_is_configured(self, settings):
        # A blank broker means the worker starts and then does nothing at all.
        assert settings.CELERY_BROKER_URL
