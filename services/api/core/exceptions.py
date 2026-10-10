"""A single error shape for the whole API.

The old backend wrapped almost every view in ``except:`` and returned
``{"message": "Something went wrong. Please try again."}`` — or a bare string, or
a nested serializer dict, or nothing. The mobile app had to guess at four
different formats.

Everything now fails the same way:

.. code-block:: json

    {
      "error": {
        "code": "validation_error",
        "message": "The request was invalid.",
        "details": {"email": ["This field is required."]}
      }
    }
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from django.core.exceptions import (
    PermissionDenied as DjangoPermissionDenied,
    ValidationError as DjangoValidationError,
)
from django.db import IntegrityError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    NotFound,
    PermissionDenied as DRFPermissionDenied,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class APIError(APIException):
    """Base class for errors this project raises deliberately."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    default_code = "error"
    default_detail = "Something went wrong."

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(detail or self.default_detail, code or self.default_code)
        # APIException's `code` argument only annotates `detail`; the envelope
        # needs the override too, otherwise every raised error reports its class
        # name instead of what it actually means.
        self.code = code or self.default_code
        self.details = details


class Conflict(APIError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"
    default_detail = "That resource already exists."


class Unprocessable(APIError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "unprocessable"
    default_detail = "The request could not be processed."


class Gone(APIError):
    """410 rather than 204.

    Used where the old API returned ``410 GONE`` after a successful delete, which
    every client read as a failure. Success is ``204``; ``410`` now means the thing
    you asked about is genuinely gone and will not be coming back.
    """

    status_code = status.HTTP_410_GONE
    default_code = "gone"
    default_detail = "This resource is no longer available."


class BusinessRuleViolation(APIError):
    """The request was well-formed but breaks a rule of the domain.

    Booking a slot in the past, cancelling someone else's booking, paying for an
    appointment you do not own. Distinct from validation: the input parsed fine.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "business_rule_violation"
    default_detail = "That action is not allowed."


def _flatten_drf_detail(detail: Any) -> tuple[str, Any]:
    """Split a DRF error into a human message and machine-readable details."""
    if isinstance(detail, dict):
        message = "The request was invalid."
        details: Any = {
            key: [str(item) for item in (value if isinstance(value, list) else [value])]
            for key, value in detail.items()
        }
        first = next(
            (
                str(item)
                for value in detail.values()
                for item in (value if isinstance(value, list) else [value])
            ),
            message,
        )
        message = first if first else message
        return message, details

    if isinstance(detail, list):
        messages = [str(item) for item in detail]
        return (messages[0] if messages else "Invalid request."), messages

    return str(detail), None


def api_exception_handler(exc: Exception, context: dict) -> Response | None:
    """DRF exception handler that emits a consistent envelope.

    Unhandled exceptions are logged with a traceback and returned as a generic
    500 — never their message, which leaks internals to anyone who can provoke
    one.
    """
    if isinstance(exc, DjangoValidationError):
        exc = Unprocessable(
            "; ".join(exc.messages) or None,
            code="validation_error",
            details=list(exc.messages),
        )
    elif isinstance(exc, Http404):
        # rest_framework's NotFound, not our APIError — otherwise a missing
        # object would be reported as a 400 and clients would treat a deleted
        # booking as a malformed request.
        exc = NotFound("Not found.", code="not_found")
    elif isinstance(exc, DjangoPermissionDenied):
        exc = DRFPermissionDenied(
            "You do not have permission to do that.", code="permission_denied"
        )
    elif isinstance(exc, IntegrityError):
        # A constraint fired. The client sent something we already have, but the
        # database message is not safe to echo.
        logger.info("Integrity error on %s: %s", context.get("request"), exc)
        exc = Conflict("That conflicts with something that already exists.")

    response = drf_exception_handler(exc, context)

    if response is None:
        logger.error(
            "Unhandled %s on %s %s\n%s",
            type(exc).__name__,
            getattr(context.get("request"), "method", "?"),
            getattr(context.get("request"), "path", "?"),
            traceback.format_exc(),
        )
        return Response(
            {
                "error": {
                    "code": "server_error",
                    "message": "Something went wrong on our end. Please try again.",
                    "details": None,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, APIError):
        code = exc.code
        message = str(exc.detail)
        details = exc.details
        if details is None and isinstance(exc.detail, (dict, list)):
            # A serializer error routed through APIError still deserves its
            # field-level breakdown, otherwise the client only sees a sentence.
            message, details = _flatten_drf_detail(exc.detail)
    else:
        code = getattr(exc, "default_code", "error")
        message, details = _flatten_drf_detail(response.data)

    response.data = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        }
    }
    return response
