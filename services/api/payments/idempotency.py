"""Making a request safe to retry.

A client on a flaky connection retries. On the payment endpoints that is not
merely wasteful — a retried `POST /payments/verify/` is a second chance to
capture, and a payment that appears twice on a statement is the sort of thing
a customer does not forgive.

The rules, and why each exists:

- **The key belongs to an account and an endpoint.** Two people on one device,
  or one person signing out and back in, must not collide.
- **The body is fingerprinted.** A *different* request wearing a used key is
  not a retry, it is a mistake. Answering it with the first response would hand
  back somebody else's receipt, which is worse than refusing.
- **The stored response is replayed byte for byte.** Recomputing it could
  produce something subtly different from what the customer was already shown.
- **A failed request is not recorded.** Only successes are worth replaying; a
  client should be free to try again after a genuine failure.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.response import Response

from payments.models import IdempotencyRecord

logger = logging.getLogger(__name__)

HEADER = "Idempotency-Key"

#: A key older than this is treated as a fresh request. A client that
#: generates a key per *attempt* rather than per *operation* should not be
#: locked out by reusing it weeks later, and a payment that succeeded weeks
#: ago is not going to be replayed into anything harmful.
DEFAULT_TTL_SECONDS = 24 * 60 * 60

#: Enough for a UUID, a ULID, or a client-invented opaque string.
MAX_KEY_LENGTH = 128


class IdempotencyConflict(Exception):
    """The same key, a different request. Refused rather than replayed."""


def fingerprint(body: Any) -> str:
    """A stable hash of the request body.

    Sorted keys, because two bodies that differ only in ordering are the same
    request and a client is not obliged to serialise a dict consistently.
    """
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _key_from(request) -> str | None:
    raw = request.headers.get(HEADER) or request.META.get("HTTP_IDEMPOTENCY_KEY")
    if not raw:
        return None

    cleaned = raw.strip()
    if not cleaned or len(cleaned) > MAX_KEY_LENGTH:
        # A malformed key is treated as no key at all rather than as a 400: the
        # endpoint must keep working for clients that do not use this feature.
        return None
    return cleaned


def replayable(endpoint: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Callable:
    """Wrap a view method so a repeat returns the first response.

    Without a key the method runs exactly as before — this adds no requirement
    to any client.
    """

    def decorate(view: Callable) -> Callable:
        @functools.wraps(view)
        def wrapper(view_self, request, *args, **kwargs):
            key = _key_from(request)
            if key is None:
                return view(view_self, request, *args, **kwargs)

            request_fingerprint = fingerprint(request.data)
            existing = IdempotencyRecord.objects.filter(
                user=request.user, endpoint=endpoint, key=key
            ).first()

            if existing is not None:
                if existing.age_seconds > ttl_seconds:
                    # Too old to be the same operation. Let it through.
                    return view(view_self, request, *args, **kwargs)

                if existing.fingerprint != request_fingerprint:
                    raise IdempotencyConflict(
                        "That idempotency key was already used for a different request."
                    )

                logger.info("Replaying %s for idempotency key %s", endpoint, key)
                return Response(existing.response_body, status=existing.response_status)

            response = view(view_self, request, *args, **kwargs)

            # Only successful responses are worth replaying. A client that
            # failed should be free to try again.
            if 200 <= response.status_code < 300:
                try:
                    with transaction.atomic():
                        IdempotencyRecord.objects.create(
                            user=request.user,
                            key=key,
                            endpoint=endpoint,
                            fingerprint=request_fingerprint,
                            response_status=response.status_code,
                            response_body=response.data,
                        )
                except IntegrityError:
                    # Two concurrent retries raced. Whoever lost replays the
                    # winner's response rather than doing the work again.
                    winner = IdempotencyRecord.objects.filter(
                        user=request.user, endpoint=endpoint, key=key
                    ).first()
                    if winner is not None:
                        return Response(winner.response_body, status=winner.response_status)

            return response

        return wrapper

    return decorate


def idempotent(endpoint: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Callable:
    """Mark a view method as safe to retry.

    A conflict becomes a 409 through the project's own error shape, rather than
    a bespoke response nobody's client knows how to read.
    """

    def decorate(view: Callable) -> Callable:
        guarded = replayable(endpoint, ttl_seconds=ttl_seconds)(view)

        @functools.wraps(view)
        def wrapper(view_self, request, *args, **kwargs):
            try:
                return guarded(view_self, request, *args, **kwargs)
            except IdempotencyConflict as conflict:
                return Response(
                    {
                        "error": {
                            "code": "idempotency_conflict",
                            "message": str(conflict),
                            "details": None,
                        }
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        return wrapper

    return decorate
