"""Verification and reset codes.

The old implementation used ``random.choice`` — a Mersenne Twister — to generate
the emailed code, and stored the code in plaintext. Mersenne Twister output is
predictable from 624 consecutive values, and a database read gave every
unexpired code away.

Here codes come from :mod:`secrets`, are hashed with SHA-256 before storage, and
expire.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1
CODE_LENGTH = 8
SIGNUP_CODE_TTL = timedelta(days=1)
RESET_CODE_TTL = timedelta(minutes=30)
RESET_CODE_LENGTH = 10
MAX_ATTEMPTS = 5


def generate_code(length: int = CODE_LENGTH) -> str:
    """A cryptographically random code drawn from an unambiguous alphabet."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def hash_code(code: str) -> str:
    """Hash a code for storage. ``secrets.compare_digest`` compares the hash."""
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def codes_match(candidate: str, stored_hash: str) -> bool:
    return secrets.compare_digest(hash_code(candidate), stored_hash)


def expiry_for(purpose: str) -> timedelta:
    """How long a code of this purpose stays valid.

    Takes the raw string rather than ``VerificationCode.Purpose`` so that
    :mod:`core` does not have to import :mod:`accounts` — which imports core.
    """
    return SIGNUP_CODE_TTL if purpose == "signup" else RESET_CODE_TTL


def expires_at(purpose: str):
    return timezone.now() + expiry_for(purpose)


def throttle_scopes_for(*scopes: str) -> dict:
    """Build a throttle scope dict for ``ScopedRateThrottle``.

    Keeps the call site readable — ``self.throttle_scope = {"throttle_scope": ...}``
    scattered across a dozen views is easy to get subtly wrong.
    """
    if len(scopes) == 1:
        return {"throttle_scope": scopes[0]}
    return {"scopes": scopes}


def ip_from_request(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def is_production() -> bool:
    from django.conf import settings

    return not settings.DEBUG and "test" not in settings.SETTINGS_MODULE
