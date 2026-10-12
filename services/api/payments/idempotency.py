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
- **The key is claimed before the work starts, not after it finishes.** This
  is the one that matters under concurrency. Recording the answer afterwards
  leaves a window in which a second request finds no record, runs the view, and
  captures the payment a second time. The unique insert at the start is the
  lock; whoever loses it either replays the winner's answer or is told to come
  back, and never does the work.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import time
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

#: How long a request that collides with an in-flight one waits for the answer
#: to appear. Long enough for a payment gateway round trip, short enough that a
#: wedged worker does not hold a web thread.
IN_PROGRESS_WAIT_SECONDS = 2.0
IN_PROGRESS_POLL_SECONDS = 0.05


class IdempotencyConflict(Exception):
    """The same key, a different request. Refused rather than replayed."""


class IdempotencyInProgress(Exception):
    """The same key, still being worked on elsewhere."""


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


def _reserve(request, endpoint: str, key: str, request_fingerprint: str, ttl_seconds: int):
    """Claim the key, or say why we cannot have it.

    Returns one of:
      - ``"mine"``: the key is reserved for this request, go and do the work.
      - a DRF ``Response``: somebody already has the answer, or the key is
        unusable.

    The insert is the lock. It happens in autocommit so a second request sees
    it immediately, rather than only after this request commits.
    """
    try:
        # The atomic block is a savepoint, not a transaction: it contains the
        # IntegrityError so that catching it does not poison an enclosing
        # transaction. On success the row is committed normally, so a
        # concurrent request sees the reservation immediately.
        with transaction.atomic():
            IdempotencyRecord.objects.create(
                user=request.user,
                key=key,
                endpoint=endpoint,
                fingerprint=request_fingerprint,
                state=IdempotencyRecord.State.IN_PROGRESS,
            )
    except IntegrityError:
        pass
    else:
        return "mine"

    existing = IdempotencyRecord.objects.filter(
        user=request.user, endpoint=endpoint, key=key
    ).first()

    if existing is None:
        # The row vanished between the collision and the read: the holder
        # rolled back or expired. Try to claim it once more.
        return "retry"

    if existing.age_seconds > ttl_seconds:
        # Too old to be the same operation. Expired frees the key outright,
        # whatever it was used for before - a client that generates one key per
        # attempt must not be locked out for good, and a stale reservation is
        # also how a worker that died mid-request stops blocking its key
        # forever.
        #
        # Checked *before* the fingerprint for that reason: a mismatch on an
        # expired row would otherwise be a conflict that never clears, because
        # the row is never deleted.
        existing.delete()
        return "retry"

    if existing.fingerprint != request_fingerprint:
        raise IdempotencyConflict("That idempotency key was already used for a different request.")

    if not existing.is_replayable:
        # Genuinely mid-flight elsewhere. On a payment this is the rare,
        # dangerous case: two verify calls for one key at the same instant.
        # Waiting briefly lets the normal case - the first request simply
        # finishing - return the real answer instead of an error.
        if _wait_for_completion(existing):
            return Response(existing.response_body, status=existing.response_status)
        raise IdempotencyInProgress("That request is still being processed. Try again in a moment.")

    logger.info("Replaying %s for idempotency key %s", endpoint, key)
    return Response(existing.response_body, status=existing.response_status)


def _wait_for_completion(record: IdempotencyRecord) -> bool:
    """Give the request holding the key a moment to finish.

    Bounded, because the caller is a web worker and the alternative to waiting
    is refusing a retry that was about to succeed. Refreshes the row rather
    than sleeping on the instance we already loaded.
    """
    deadline = time.monotonic() + IN_PROGRESS_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(IN_PROGRESS_POLL_SECONDS)
        record.refresh_from_db()
        if record.state == IdempotencyRecord.State.COMPLETE:
            return True
        if record.age_seconds > DEFAULT_TTL_SECONDS:
            # The holder is not coming back. Treat it as expired.
            return False
    return False


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

            # At most twice: once to claim, once more if the row we collided
            # with was stale and has just been cleared.
            for _attempt in range(2):
                outcome = _reserve(request, endpoint, key, request_fingerprint, ttl_seconds)
                if outcome != "retry":
                    break
            else:
                raise IdempotencyConflict("That idempotency key could not be claimed. Try again.")

            if outcome != "mine":
                return outcome

            record = IdempotencyRecord.objects.get(user=request.user, endpoint=endpoint, key=key)

            try:
                response = view(view_self, request, *args, **kwargs)
            except Exception:
                # Give the key back. A crash is not a result, and the client is
                # entitled to retry it.
                record.delete()
                raise

            if 200 <= response.status_code < 300:
                record.state = IdempotencyRecord.State.COMPLETE
                record.response_status = response.status_code
                record.response_body = response.data
                record.save(update_fields=["state", "response_status", "response_body"])
            else:
                # Only successful responses are worth replaying. A client that
                # failed should be free to try again, so the key is released
                # rather than pinned to this failure.
                record.delete()

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
            except IdempotencyInProgress as busy:
                # Also a 409, and deliberately the same code: from the client's
                # point of view "come back shortly" and "that key is wrong" are
                # both "do not retry this exact request again".
                return Response(
                    {
                        "error": {
                            "code": "idempotency_in_progress",
                            "message": str(busy),
                            "details": None,
                        }
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        return wrapper

    return decorate
