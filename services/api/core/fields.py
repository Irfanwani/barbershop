"""Transparent field-level encryption for data that must never sit in plaintext.

Provider bank account numbers qualify: they are financial identifiers, they are
stored in the same database as profile photos, and the old schema returned them
verbatim through a ``fields = '__all__'`` serializer.

Encryption is Fernet (AES-128-CBC + HMAC-SHA256) from ``cryptography``. The key
comes from ``FIELD_ENCRYPTION_KEY`` and must be set explicitly — there is no
default, because a default key is the same as no encryption at all.

The trade-off is honest and worth stating: encrypted columns cannot be queried
or indexed. That is fine here, because these fields are only ever compared for
equality against themselves and written once.

Rotating the key makes existing values unreadable. Write a management command to
re-encrypt before you rotate.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


@lru_cache(maxsize=4)
def _fernet(key_material: str) -> Fernet:
    """Build a Fernet from arbitrary key material.

    ``FIELD_ENCRYPTION_KEY`` is whatever the operator put in the environment —
    a Fernet key, a password, a UUID. Rather than demand one exact format, it is
    hashed to 32 bytes. Losing the original value still loses the data; the point
    is that anything reasonable works as input.
    """
    if not key_material:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY is not set. Provider bank details cannot be "
            "stored without it. See services/api/.env.example."
        )
    digest = hashlib.sha256(key_material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def get_fernet() -> Fernet:
    return _fernet(settings.FIELD_ENCRYPTION_KEY)


def encrypt(plaintext: str) -> str:
    return get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    try:
        return get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Stored value could not be decrypted. Either the data is corrupt or "
            "FIELD_ENCRYPTION_KEY has been rotated without re-encrypting."
        ) from exc


class EncryptedTextField(models.TextField):
    """A ``TextField`` whose contents are encrypted on the way into the database."""

    description = "Text encrypted at rest with Fernet"

    def db_type(self, connection):
        return "text"

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        try:
            return decrypt(value)
        except ValueError:
            # Returning the raw ciphertext beats raising: a single unreadable row
            # should not make an admin page 500. The corruption is still visible.
            return f"<undecryptable:{len(value)}>"

    def to_python(self, value):
        if value is None:
            return value
        # Values arriving from a form have not been through the database layer.
        return value

    def get_prep_value(self, value):
        if value is None:
            return None
        if isinstance(value, EncryptedValue):
            return value.ciphertext
        if value == "":
            return ""
        # Already ciphertext? Passing it back through would double-encrypt on
        # every partial update, so detect the token and leave it alone.
        if isinstance(value, str) and value.startswith("gAAAA"):
            return value
        return encrypt(str(value))

    def value_to_string(self, obj):
        return self.value_from_object(obj)


class EncryptedValue(str):
    """A ciphertext wrapper, for the rare case where you want it explicit."""

    __slots__ = ("ciphertext",)

    ciphertext: str

    def __new__(cls, plaintext: str) -> EncryptedValue:
        instance = super().__new__(cls, "")
        instance.ciphertext = encrypt(plaintext)
        return instance


def mask(value: str, keep: int = 4) -> str:
    """Mask a financial identifier for display.

    ``4111111111111111`` becomes ``••••••••••••1111``. Enough for someone to
    recognise their own account; useless to anyone who obtains the database.
    """
    if not value:
        return ""
    # `value[-0:]` is the whole string, not the empty one — which would have made
    # keep=0 (mask everything, for an IFSC code) return the value in the clear.
    if keep <= 0 or len(value) <= keep:
        return "•" * len(value)
    return "•" * (len(value) - keep) + value[-keep:]
