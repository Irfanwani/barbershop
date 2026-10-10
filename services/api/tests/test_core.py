"""Tests for the shared building blocks in :mod:`core`.

These matter more than their line count suggests: the exception handler is what
turns an unhandled bug into a 500 without leaking internals, and the permission
classes are the only thing standing between one user's booking and another's.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import (
    PermissionDenied as DjangoPermissionDenied,
    ValidationError as DjangoValidationError,
)
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.test import APIRequestFactory

from accounts.models import User
from core import exceptions as exc
from core.fields import EncryptedTextField, decrypt, encrypt, mask
from core.pagination import CompactPagination, DefaultPagination
from core.permissions import IsCustomer, IsOwner, IsProvider, IsVerified, ReadOnly
from core.tokens import codes_match, expiry_for, generate_code, hash_code
from tests.factories import make_profile, make_provider_user, make_user

factory = APIRequestFactory()


def error_of(response):
    assert "error" in response.data, response.data
    assert set(response.data["error"]) == {"code", "message", "details"}
    return response.data["error"]


# ---------------------------------------------------------------------------
# Exception handler
# ---------------------------------------------------------------------------


def handle(exc_obj, request=None):
    request = request or factory.get("/")
    return exc.api_exception_handler(exc_obj, {"request": request})


class TestExceptionHandler:
    def test_api_error_keeps_its_own_code_and_message(self):
        response = handle(exc.Conflict("That email is already registered."))

        assert response.status_code == status.HTTP_409_CONFLICT
        assert error_of(response) == {
            "code": "conflict",
            "message": "That email is already registered.",
            "details": None,
        }

    def test_serializer_errors_become_field_details(self):
        response = handle(exc.Unprocessable(detail={"email": ["This field is required."]}))

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        error = error_of(response)
        assert error["details"] == {"email": ["This field is required."]}
        assert "required" in error["message"]

    def test_not_found_is_normalised(self):
        response = handle(Http404())

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert error_of(response)["code"] == "not_found"

    def test_permission_denied_is_normalised(self):
        response = handle(DjangoPermissionDenied())

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert error_of(response)["code"] == "permission_denied"

    @pytest.mark.django_db
    def test_django_validation_error_becomes_422(self):
        response = handle(DjangoValidationError("That slot is in the past."))

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert error_of(response)["code"] == "validation_error"

    def test_integrity_error_does_not_leak_the_database_message(self):
        from django.db import IntegrityError

        response = handle(
            IntegrityError(
                'duplicate key value violates unique constraint "accounts_user_email_key"'
            )
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        message = error_of(response)["message"]
        assert "accounts_user_email_key" not in message

    def test_unhandled_exception_becomes_a_generic_500(self):
        response = handle(RuntimeError("connection pool exhausted at 10.0.0.4"))

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        error = error_of(response)
        assert error["code"] == "server_error"
        assert "10.0.0.4" not in error["message"], "internals must not reach the client"

    def test_every_error_has_the_same_shape(self):
        """The old API returned four different error formats. There is one now."""
        shapes = [
            handle(exc.Conflict("x")).data,
            handle(Http404()).data,
            handle(exc.Unprocessable(detail={"a": ["b"]})).data,
            handle(RuntimeError("boom")).data,
        ]
        for shape in shapes:
            assert set(shape) == {"error"}
            assert set(shape["error"]) == {"code", "message", "details"}

    def test_gone_is_410_and_documented_as_such(self):
        response = handle(exc.Gone())
        assert response.status_code == status.HTTP_410_GONE


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPermissions:
    def test_is_provider_allows_a_set_up_provider(self):
        request = factory.get("/")
        request.user = make_provider_user()
        make_profile(request.user)

        assert IsProvider().has_permission(request, None)
        assert not IsCustomer().has_permission(request, None)

    def test_is_provider_rejects_a_customer(self):
        request = factory.get("/")
        request.user = make_user()

        assert not IsProvider().has_permission(request, None)
        assert IsCustomer().has_permission(request, None)

    def test_is_provider_requires_a_profile_not_just_a_role(self):
        """A provider mid-onboarding has the role but no shop yet."""
        request = factory.get("/")
        request.user = make_provider_user()

        assert not IsProvider().has_permission(request, None)

        make_profile(request.user)
        assert IsProvider().has_permission(request, None)

    def test_is_verified_gates_on_the_verified_flag(self):
        request = factory.get("/")

        request.user = make_user(verified=False)
        assert not IsVerified().has_permission(request, None)

        request.user = make_user(verified=True)
        assert IsVerified().has_permission(request, None)

    def test_anonymous_user_fails_everything(self):
        from django.contrib.auth.models import AnonymousUser

        request = factory.get("/")
        request.user = AnonymousUser()

        for permission in (IsProvider(), IsCustomer(), IsVerified()):
            assert not permission.has_permission(request, None)

    def test_is_owner_allows_the_owner_of_the_record(self):
        request = factory.get("/")
        owner = make_user()
        request.user = owner
        profile = make_profile(owner)

        assert IsOwner().has_object_permission(request, None, profile)

    def test_is_owner_rejects_someone_elses_record(self):
        request = factory.get("/")
        request.user = make_user()

        assert not IsOwner().has_object_permission(request, None, make_profile())

    def test_is_owner_rejects_objects_without_a_user(self):
        request = factory.get("/")
        request.user = make_user()

        assert not IsOwner().has_object_permission(request, None, object())

    def test_read_only_allows_get_and_rejects_post(self):
        assert ReadOnly().has_permission(factory.get("/"), None)
        assert not ReadOnly().has_permission(factory.post("/", {}), None)


# ---------------------------------------------------------------------------
# Encrypted fields
# ---------------------------------------------------------------------------


class TestEncryptedField:
    def test_round_trip(self):
        assert decrypt(encrypt("hello")) == "hello"

    def test_ciphertext_is_url_safe_ascii(self):
        assert encrypt("hello").isascii()

    def test_two_encryptions_of_the_same_value_differ(self):
        """Fernet includes a random IV, so equal plaintexts are not equal rows."""
        assert encrypt("same") != encrypt("same")

    def test_wrong_key_cannot_decrypt(self, settings):
        value = encrypt("secret")
        settings.FIELD_ENCRYPTION_KEY = "a completely different key"

        with pytest.raises(ValueError, match="could not be decrypted"):
            decrypt(value)

    def test_field_declares_a_text_column(self):
        assert EncryptedTextField().db_type(None) == "text"

    def test_empty_value_is_not_encrypted(self):
        """An empty string must stay empty, not become a token."""
        assert EncryptedTextField().get_prep_value("") == ""

    def test_none_stays_none(self):
        assert EncryptedTextField().get_prep_value(None) is None

    def test_a_ciphertext_passed_back_is_not_re_encrypted(self):
        field = EncryptedTextField()
        ciphertext = encrypt("hello")

        assert field.get_prep_value(ciphertext) == ciphertext


class TestMask:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("4111111111111111", "•" * 12 + "1111"),
            ("1234", "••••"),
            ("12", "••"),
            ("", ""),
        ],
    )
    def test_mask(self, value, expected):
        assert mask(value) == expected

    def test_mask_can_hide_everything(self):
        assert mask("HDFC0001234", keep=0) == "•" * 11


# ---------------------------------------------------------------------------
# Verification codes
# ---------------------------------------------------------------------------


class TestCodeHelpers:
    def test_codes_are_the_right_length_and_alphabet(self):
        code = generate_code()
        assert len(code) == 8
        assert code.isalnum()

    def test_reset_codes_are_longer(self):
        assert len(generate_code(expiry_for("reset") and 10)) == 10

    def test_hashing_is_stable_and_case_insensitive(self):
        assert hash_code("abc12345") == hash_code("ABC12345")

    def test_codes_match_is_exact(self):
        stored = hash_code(generate_code())
        assert codes_match("abc12345", stored) is (hash_code("abc12345") == stored)

    def test_expiry_depends_on_purpose(self):
        assert expiry_for("signup") > expiry_for("reset")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    def test_page_size_is_capped(self):
        """Otherwise a client can ask for the entire table in one request."""
        assert DefaultPagination().max_page_size == 100

    def test_compact_pagination_has_a_smaller_page(self):
        assert CompactPagination().page_size == 10


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class TestPublicMediaStorage:
    def test_uploads_are_not_overwritten(self, settings):
        from core.storage import PublicMediaStorage

        settings.AWS_STORAGE_BUCKET_NAME = "barbershop-media"
        storage = PublicMediaStorage()

        assert storage.file_overwrite is False
        assert storage.location == "media"

    def test_bucket_comes_from_settings(self, settings):
        from core.storage import PublicMediaStorage

        settings.AWS_STORAGE_BUCKET_NAME = "another-bucket"
        assert PublicMediaStorage().bucket_name == "another-bucket"


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


class TestMoneyHelpers:
    def test_to_minor_rejects_float_noise(self):
        from core.money import to_minor

        assert to_minor(0.1 + 0.2) == 30  # not 29.99999...

    def test_to_major_always_shows_two_decimals(self):
        from core.money import to_major

        assert to_major(25000) == "250.00"
        assert to_major(5) == "0.05"


@pytest.mark.django_db
def test_user_str_is_the_username():
    assert str(make_user("someone")) == "someone"


def test_role_constants_are_stable():
    """These strings are stored in the database and sent over the wire."""
    assert User._meta.get_field("role").choices[0][0] == "customer"


def test_api_exception_base_class_defaults():
    assert issubclass(exc.APIError, APIException)
    assert exc.APIError.default_code == "error"
