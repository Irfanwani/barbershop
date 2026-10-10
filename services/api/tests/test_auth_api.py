"""Tests for ``/api/v1/auth/`` and ``/api/v1/me/``."""

from __future__ import annotations

import pytest
from django.core import mail
from django.test import override_settings
from knox.models import AuthToken

from accounts.models import Role, User, VerificationCode
from accounts.serializers import AccountStateSerializer
from core.tokens import codes_match, hash_code
from tests.factories import auth_header, logged_in, make_user

pytestmark = pytest.mark.django_db

V1 = "/api/v1"


def latest_code(user: User, purpose: str) -> str:
    """The code that was emailed, recovered from the sent message.

    Tests assert on what the user actually receives rather than reaching into
    the database for the hash.
    """
    body = mail.outbox[-1].body
    return next(
        line.strip() for line in body.splitlines() if line.strip() and line.strip().isalnum()
    )


def register(client, **overrides):
    payload = {
        "username": "newcomer",
        "email": "newcomer@example.com",
        "password": "Str0ngPass!23",
        "role": "customer",
    }
    payload.update(overrides)
    return client.post(f"{V1}/auth/register/", payload, content_type="application/json")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegister:
    def test_creates_an_account(self):
        client = __import__("django").test.Client()
        response = register(client)

        assert response.status_code == 201, response.content
        assert User.objects.filter(username="newcomer").exists()

    def test_returns_a_token_and_the_account_state(self):
        from django.test import Client

        response = register(Client())

        body = response.json()
        assert body["token"]
        assert body["user"]["username"] == "newcomer"
        assert body["user"]["role"] == Role.CUSTOMER
        assert body["user"]["is_verified"] is False
        assert body["verification_required"] is True

    def test_emails_a_verification_code(self):
        from django.test import Client

        register(Client())

        assert len(mail.outbox) == 1
        assert "Confirm your" in mail.outbox[0].subject
        assert "newcomer@example.com" in mail.outbox[0].to

    def test_never_returns_the_password_hash(self):
        from django.test import Client

        body = register(Client()).json()
        assert "password" not in body["user"]
        assert not any("password" in str(value) for value in body["user"].values())

    def test_rejects_a_duplicate_username_case_insensitively(self):
        from django.test import Client

        make_user("Taken")
        response = register(Client(), username="taken", email="other@example.com")

        assert response.status_code == 400
        assert "username" in response.json()["error"]["details"]

    def test_rejects_a_duplicate_email_case_insensitively(self):
        from django.test import Client

        make_user("first", email="dupe@example.com")
        response = register(Client(), username="second", email="DUPE@example.com")

        assert response.status_code == 400
        assert "email" in response.json()["error"]["details"]

    @override_settings(
        AUTH_PASSWORD_VALIDATORS=[
            {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
            {
                "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
                "OPTIONS": {"min_length": 8},
            },
        ]
    )
    def test_rejects_a_weak_password(self):
        """The test settings disable validators for speed; this proves they work."""
        from django.test import Client

        response = register(Client(), password="password")

        assert response.status_code == 400
        assert "password" in response.json()["error"]["details"]

    def test_rejects_a_malformed_email(self):
        from django.test import Client

        response = register(Client(), email="not-an-email")
        assert response.status_code == 400

    def test_can_register_directly_as_a_provider(self):
        from django.test import Client

        response = register(Client(), role="provider")

        assert response.status_code == 201
        assert response.json()["user"]["role"] == Role.PROVIDER

    def test_error_uses_the_standard_envelope(self):
        from django.test import Client

        body = register(Client(), email="bad").json()
        assert set(body) == {"error"}
        assert set(body["error"]) == {"code", "message", "details"}


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


class TestLogin:
    def test_logs_in_with_a_username(self):
        from django.test import Client

        client = Client()
        make_user("jane", password="Str0ngPass!23")
        body = client.post(
            f"{V1}/auth/login/",
            {"identifier": "jane", "password": "Str0ngPass!23"},
            content_type="application/json",
        ).json()

        assert body["token"]
        assert body["user"]["username"] == "jane"

    def test_logs_in_with_an_email_address(self):
        from django.test import Client

        make_user("jane", email="jane@example.com", password="Str0ngPass!23")
        response = Client().post(
            f"{V1}/auth/login/",
            {"identifier": "jane@example.com", "password": "Str0ngPass!23"},
            content_type="application/json",
        )

        assert response.status_code == 200

    def test_rejects_a_wrong_password_without_saying_which_part(self):
        from django.test import Client

        make_user("jane", password="Str0ngPass!23")
        body = (
            Client()
            .post(
                f"{V1}/auth/login/",
                {"identifier": "jane", "password": "wrong"},
                content_type="application/json",
            )
            .json()
        )

        assert "Incorrect credentials" in str(body)

    def test_unknown_account_and_wrong_password_are_indistinguishable(self):
        """Otherwise the endpoint is a way to enumerate usernames."""
        from django.test import Client

        make_user("jane", password="Str0ngPass!23")
        client = Client()

        unknown = client.post(
            f"{V1}/auth/login/",
            {"identifier": "nobody", "password": "Str0ngPass!23"},
            content_type="application/json",
        )
        wrong = client.post(
            f"{V1}/auth/login/",
            {"identifier": "jane", "password": "wrong-one"},
            content_type="application/json",
        )

        assert unknown.status_code == wrong.status_code == 400
        assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]

    def test_disabled_account_cannot_log_in(self):
        from django.test import Client

        user = make_user("suspended", password="Str0ngPass!23")
        user.is_active = False
        user.save()

        response = Client().post(
            f"{V1}/auth/login/",
            {"identifier": "suspended", "password": "Str0ngPass!23"},
            content_type="application/json",
        )
        assert "disabled" in response.json()["error"]["message"]

    def test_a_brand_new_customer_is_not_reported_as_a_provider(self):
        """The old `is_barber` flag came back True for users with no profile."""
        from django.test import Client

        make_user("fresh", password="Str0ngPass!23")
        body = (
            Client()
            .post(
                f"{V1}/auth/login/",
                {"identifier": "fresh", "password": "Str0ngPass!23"},
                content_type="application/json",
            )
            .json()
        )

        assert body["user"]["role"] == Role.CUSTOMER
        assert body["user"]["has_provider_profile"] is False


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


class TestEmailVerification:
    def _registered(self, client):
        response = register(client, username="pending", email="pending@example.com")
        return response.json()["token"]

    def test_the_right_code_verifies_the_account(self):
        from django.test import Client

        client = Client()
        token = self._registered(client)
        code = latest_code(User.objects.get(username="pending"), "signup")

        response = client.post(
            f"{V1}/auth/verify-email/",
            {"code": code},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        assert response.json()["verified"] is True
        assert User.objects.get(username="pending").is_verified

    def test_the_code_is_single_use(self):
        from django.test import Client

        client = Client()
        token = self._registered(client)
        code = latest_code(User.objects.get(username="pending"), "signup")

        client.post(
            f"{V1}/auth/verify-email/",
            {"code": code},
            content_type="application/json",
            **auth_header(token),
        )
        second = client.post(
            f"{V1}/auth/verify-email/",
            {"code": code},
            content_type="application/json",
            **auth_header(token),
        )

        assert second.status_code == 400

    def test_a_wrong_code_is_rejected(self):
        from django.test import Client

        client = Client()
        token = self._registered(client)
        response = client.post(
            f"{V1}/auth/verify-email/",
            {"code": "ZZZZZZZZ"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert not User.objects.get(username="pending").is_verified

    def test_attempts_are_capped(self):
        from django.test import Client

        client = Client()
        token = self._registered(client)
        user = User.objects.get(username="pending")

        for _ in range(5):
            client.post(
                f"{V1}/auth/verify-email/",
                {"code": "ZZZZZZZZ"},
                content_type="application/json",
                **auth_header(token),
            )

        record = VerificationCode.objects.filter(user=user).first()
        assert record is None, "the record is deleted once attempts run out"

    def test_resending_replaces_the_old_code(self):
        from django.test import Client

        client = Client()
        token = self._registered(client)
        old = latest_code(User.objects.get(username="pending"), "signup")

        client.post(f"{V1}/auth/resend-verification/", {}, **auth_header(token))
        new = latest_code(User.objects.get(username="pending"), "signup")

        assert old != new
        assert (
            VerificationCode.objects.filter(
                user__username="pending", consumed_at__isnull=True
            ).count()
            == 1
        )

    def test_resending_says_so_when_already_verified(self):
        from django.test import Client

        client = Client()
        token = self._registered(client)
        user = User.objects.get(username="pending")
        user.mark_verified()
        user.save()

        response = client.post(f"{V1}/auth/resend-verification/", {}, **auth_header(token))
        assert response.json()["verified"] is True

    def test_verification_requires_authentication(self):
        from django.test import Client

        response = Client().post(
            f"{V1}/auth/verify-email/", {"code": "ABCD1234"}, content_type="application/json"
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


class TestPasswordReset:
    def test_sends_a_code(self):
        from django.test import Client

        make_user("forgetful", email="forgetful@example.com")
        response = Client().post(
            f"{V1}/auth/password-reset/request/",
            {"email": "forgetful@example.com"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert len(mail.outbox) == 1
        assert "Reset your" in mail.outbox[0].subject

    def test_an_unknown_address_gives_the_same_answer(self):
        """The old endpoint said "Please provide a registered email address"."""
        from django.test import Client

        make_user("member", email="member@example.com")
        client = Client()

        known = client.post(
            f"{V1}/auth/password-reset/request/",
            {"email": "member@example.com"},
            content_type="application/json",
        )
        unknown = client.post(
            f"{V1}/auth/password-reset/request/",
            {"email": "nobody@example.com"},
            content_type="application/json",
        )

        assert known.status_code == unknown.status_code == 200
        assert known.json()["message"] == unknown.json()["message"]
        assert len(mail.outbox) == 1, "no email should go to an unknown address"

    def test_code_changes_the_password_and_returns_a_token(self):
        from django.test import Client

        user = make_user("resetme", email="resetme@example.com", password="Str0ngPass!23")
        client = Client()
        client.post(
            f"{V1}/auth/password-reset/request/",
            {"email": user.email},
            content_type="application/json",
        )
        code = latest_code(user, "reset")

        response = client.post(
            f"{V1}/auth/password-reset/confirm/",
            {"email": user.email, "code": code, "new_password": "Different!2345"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["token"]
        user.refresh_from_db()
        assert user.check_password("Different!2345")

    def test_resetting_invalidates_every_existing_session(self):
        """Whoever prompted the reset may not be the account holder."""
        from django.test import Client

        user = make_user("resetme", email="resetme@example.com", password="Str0ngPass!23")
        AuthToken.objects.create(user)
        AuthToken.objects.create(user)

        client = Client()
        client.post(
            f"{V1}/auth/password-reset/request/",
            {"email": user.email},
            content_type="application/json",
        )
        client.post(
            f"{V1}/auth/password-reset/confirm/",
            {
                "email": user.email,
                "code": latest_code(user, "reset"),
                "new_password": "Different!2345",
            },
            content_type="application/json",
        )

        assert AuthToken.objects.filter(user=user).count() == 1, "only the new session survives"

    def test_a_wrong_code_does_not_change_the_password(self):
        from django.test import Client

        user = make_user("resetme", email="resetme@example.com", password="Str0ngPass!23")
        client = Client()
        client.post(
            f"{V1}/auth/password-reset/request/",
            {"email": user.email},
            content_type="application/json",
        )

        response = client.post(
            f"{V1}/auth/password-reset/confirm/",
            {"email": user.email, "code": "ZZZZZZZZZZ", "new_password": "Different!2345"},
            content_type="application/json",
        )

        assert response.status_code == 400
        user.refresh_from_db()
        assert user.check_password("Str0ngPass!23")


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


class TestLogout:
    def test_revokes_only_the_current_token(self):
        from django.test import Client

        user = make_user("two-sessions", password="Str0ngPass!23")
        _, first_token = AuthToken.objects.create(user)
        AuthToken.objects.create(user)

        response = Client().post(f"{V1}/auth/logout/", **auth_header(first_token))

        assert response.status_code == 204
        assert AuthToken.objects.filter(user=user).count() == 1
        assert AuthToken.objects.filter(user=user).count() == 1

    def test_logout_all_revokes_every_token(self):
        from django.test import Client

        user = make_user("two-sessions", password="Str0ngPass!23")
        AuthToken.objects.create(user)
        _, second_token = AuthToken.objects.create(user)

        Client().post(f"{V1}/auth/logout-all/", **auth_header(second_token))

        assert AuthToken.objects.filter(user=user).count() == 0

    def test_logout_requires_a_token(self):
        from django.test import Client

        assert Client().post(f"{V1}/auth/logout/").status_code == 401


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------


class TestMe:
    def test_returns_the_account_and_its_onboarding_state(self):

        user = make_user("me-user")
        client, token = logged_in(user)

        body = client.get(f"{V1}/me/", **auth_header(token)).json()

        assert body["username"] == "me-user"
        assert body["role"] == Role.CUSTOMER
        assert body["is_verified"] is True
        assert body["onboarding_complete"] is True

    def test_requires_authentication(self):
        from django.test import Client

        assert Client().get(f"{V1}/me/").status_code == 401

    def test_patch_updates_the_account(self):

        user = make_user("me-user")
        client, token = logged_in(user)

        response = client.patch(
            f"{V1}/me/",
            {"first_name": "Jane", "phone": "+911234567890"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        user.refresh_from_db()
        assert user.first_name == "Jane"

    def test_delete_removes_the_account(self):

        user = make_user("me-user")
        client, token = logged_in(user)

        assert client.delete(f"{V1}/me/", **auth_header(token)).status_code == 204
        assert not User.objects.filter(pk=user.pk).exists()

    def test_change_password_requires_the_current_one(self):

        client, token = logged_in(make_user("me-user"))

        response = client.post(
            f"{V1}/me/password/",
            {"current_password": "not-it", "new_password": "Different!2345"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert "current_password" in response.json()["error"]["details"]


class TestCustomerProfile:
    def test_defaults_to_an_empty_profile(self):

        client, token = logged_in(make_user("me-user"))

        body = client.get(f"{V1}/me/profile/", **auth_header(token)).json()

        assert body["has_location"] is False
        assert body["coords"] is None

    def test_saves_a_location(self):

        client, token = logged_in(make_user("me-user"))

        response = client.put(
            f"{V1}/me/profile/",
            {
                "address": "Connaught Place, New Delhi",
                "about": "Prefer afternoon cuts",
                "coords": {"latitude": 28.6139, "longitude": 77.2090},
            },
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        assert response.json()["has_location"] is True

    def test_rejects_impossible_coordinates(self):

        client, token = logged_in(make_user("me-user"))

        response = client.put(
            f"{V1}/me/profile/",
            {"coords": {"latitude": 999, "longitude": 0}},
            content_type="application/json",
            **auth_header(token),
        )
        assert response.status_code == 400

    def test_accepts_geojson(self):

        client, token = logged_in(make_user("me-user"))

        response = client.put(
            f"{V1}/me/profile/",
            {"coords": {"type": "Point", "coordinates": [77.2090, 28.6139]}},
            content_type="application/json",
            **auth_header(token),
        )
        assert response.status_code == 200


class TestPushTokens:
    def test_registering_a_token(self):

        client, token = logged_in(make_user("me-user"))

        response = client.post(
            f"{V1}/me/push-tokens/",
            {"token": "ExponentPushToken[abc]", "platform": "android"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 201

    def test_re_registering_moves_the_token_to_the_new_account(self):
        """Re-installing on a shared device must not orphan the token."""

        first = make_user("one")
        second = make_user("two")

        for user in (first, second):
            client, token = logged_in(user)
            client.post(
                f"{V1}/me/push-tokens/",
                {"token": "ExponentPushToken[shared]"},
                content_type="application/json",
                **auth_header(token),
            )

        assert first.push_tokens.count() == 0
        assert second.push_tokens.count() == 1

    def test_a_token_can_be_removed(self):

        user = make_user("me-user")
        client, token = logged_in(user)
        push = user.push_tokens.create(token="ExponentPushToken[abc]")

        response = client.delete(f"{V1}/me/push-tokens/{push.id}/", **auth_header(token))

        assert response.status_code == 204
        assert user.push_tokens.count() == 0


def test_account_state_serializer_matches_the_model():
    """The flags the app routes on must agree with the model's own rules."""
    user = make_user("state", verified=False)
    assert AccountStateSerializer(user).data["onboarding_complete"] is False

    user.mark_verified()
    assert AccountStateSerializer(user).data["onboarding_complete"] is True


def test_hashed_code_comparison_is_case_insensitive():
    assert codes_match("abcdefgh", hash_code("ABCDEFGH"))
