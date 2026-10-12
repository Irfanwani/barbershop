"""Notification preferences live on the account, not the device.

The app kept them in local storage while the reminder task read flags on the
profile, so the two could disagree — somebody who turned reminders off on one
phone kept getting them on another. That is exactly the complaint that caused
the single-app rebuild.
"""

from __future__ import annotations

import json

import pytest

from accounts.models import (
    DEFAULT_PREFERENCES,
    NotificationKey,
    notification_preferences,
    wants_notification,
)
from tests.factories import auth_header, logged_in, make_profile, make_user

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
PREFERENCES = f"{V1}/me/notification-preferences/"


def a_customer():
    user = make_user()
    make_profile(user)
    client, token = logged_in(user)
    return user, client, token


def put_preferences(client, token, wanted):
    """Send JSON, not a form.

    A form-encoded PUT cannot express a boolean map, and the 415 that comes
    back is a fine illustration of why.
    """
    return client.put(
        PREFERENCES,
        json.dumps({"preferences": wanted}),
        content_type="application/json",
        **auth_header(token),
    )


class TestReading:
    def test_an_account_with_no_opinion_gets_the_defaults(self):
        user, _client, _token = a_customer()

        assert notification_preferences(user) == DEFAULT_PREFERENCES

    def test_nothing_is_opted_in_on_someones_behalf(self):
        """The only reason a preferences screen is trustworthy."""
        assert DEFAULT_PREFERENCES[NotificationKey.OFFERS_AND_PROMOTIONS] is False
        assert DEFAULT_PREFERENCES[NotificationKey.NEW_SHOPS_NEARBY] is False
        assert DEFAULT_PREFERENCES[NotificationKey.PRODUCT_NEWS] is False

    def test_it_needs_a_signed_in_account(self):
        from django.test import Client

        assert Client().get(PREFERENCES).status_code in (401, 403)


class TestChanging:
    def test_a_change_is_stored(self):
        user, client, token = a_customer()

        response = put_preferences(client, token, {"bookingReminders": False})

        assert response.status_code == 200
        assert response.json()["preferences"]["bookingReminders"] is False
        assert wants_notification(user, NotificationKey.BOOKING_REMINDERS) is False

    def test_a_change_made_on_one_device_is_the_answer_on_another(self):
        """The whole point. A second client reads the same account."""
        _user, client, token = a_customer()
        put_preferences(client, token, {"offersAndPromotions": True})

        # A different device, same account, same server.
        other_device = client_class()()
        reread = other_device.get(PREFERENCES, **auth_header(token))

        assert reread.json()["preferences"]["offersAndPromotions"] is True

    def test_confirmations_cannot_be_switched_off(self):
        _user, client, token = a_customer()

        response = put_preferences(client, token, {"bookingConfirmations": False})

        assert response.json()["preferences"]["bookingConfirmations"] is True

    def test_messages_cannot_be_switched_off(self):
        _user, client, token = a_customer()
        response = put_preferences(client, token, {"bookingChanges": False})
        assert response.json()["preferences"]["bookingChanges"] is True

    def test_an_unknown_category_is_refused(self):
        _user, client, token = a_customer()
        response = put_preferences(client, token, {"rocketLaunches": True})
        assert response.status_code == 400

    def test_a_partial_update_leaves_the_rest_alone(self):
        _user, client, token = a_customer()

        put_preferences(client, token, {"productNews": True})
        put_preferences(client, token, {"bookingReminders": False})

        preferences = client.get(PREFERENCES, **auth_header(token)).json()["preferences"]
        assert preferences["productNews"] is True
        assert preferences["bookingReminders"] is False

    def test_switching_back_on_works(self):
        user, client, token = a_customer()
        put_preferences(client, token, {"bookingReminders": False})
        put_preferences(client, token, {"bookingReminders": True})

        assert wants_notification(user, NotificationKey.BOOKING_REMINDERS) is True


class TestTheReminderTaskCannotDisagree:
    def test_turning_reminders_off_updates_the_flag_the_task_reads(self):
        user, client, token = a_customer()

        put_preferences(client, token, {"bookingReminders": False})

        profile = user.provider_profile
        profile.refresh_from_db()
        assert profile.reminders_enabled is False
        assert wants_notification(user, NotificationKey.BOOKING_REMINDERS) is False

    def test_and_the_other_way_round(self):
        user, client, token = a_customer()

        put_preferences(client, token, {"bookingReminders": False})
        put_preferences(client, token, {"bookingReminders": True})

        profile = user.provider_profile
        profile.refresh_from_db()
        assert profile.reminders_enabled is True


def client_class():
    from django.test import Client

    return Client
