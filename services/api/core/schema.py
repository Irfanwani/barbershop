"""Shared OpenAPI responses.

Every endpoint in this project fails the same way, so the shape is declared
once here rather than copied into thirty-odd ``@extend_schema`` calls that would
drift apart within a week.
"""

from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, OpenApiResponse

ERROR_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Stable machine-readable code, e.g. `business_rule_violation`.",
                    "example": "validation_error",
                },
                "message": {
                    "type": "string",
                    "description": "A sentence safe to show a user.",
                    "example": "That slot is already taken. Pick another time.",
                },
                "details": {
                    "nullable": True,
                    "description": "Field-level detail when there is any; null otherwise.",
                    "example": {"starts_at": ["This field is required."]},
                },
            },
            "required": ["code", "message", "details"],
        }
    },
    "required": ["error"],
}

BAD_REQUEST = OpenApiResponse(
    ERROR_SCHEMA,
    "Malformed request, or one that breaks a business rule",
    examples=[
        OpenApiExample(
            "Validation",
            summary="A field is missing or the wrong shape",
            value={
                "error": {
                    "code": "validation_error",
                    "message": "This field is required.",
                    "details": {"starts_at": ["This field is required."]},
                }
            },
        ),
        OpenApiExample(
            "Business rule",
            summary="Well-formed, but not allowed right now",
            value={
                "error": {
                    "code": "business_rule_violation",
                    "message": "That slot is already taken. Pick another time.",
                    "details": None,
                }
            },
        ),
    ],
)

# OpenApiResponse is keyed by status code in the `responses` dict, so these are
# plain values rather than status-carrying objects.

UNAUTHORIZED = OpenApiResponse(ERROR_SCHEMA, "No token, or the token has expired")
FORBIDDEN = OpenApiResponse(ERROR_SCHEMA, "Authenticated, but not allowed")
NOT_FOUND = OpenApiResponse(
    ERROR_SCHEMA,
    "No such resource, or not yours to see. Deliberately indistinguishable.",
)
CONFLICT = OpenApiResponse(ERROR_SCHEMA, "That already exists")
THROTTLED = OpenApiResponse(
    {"type": "object", "properties": {"detail": {"type": "string"}}},
    "Too many attempts. Slow down.",
)
SERVER_ERROR = OpenApiResponse(
    ERROR_SCHEMA,
    "Something went wrong on our end. The message is deliberately uninformative.",
)

#: What every authenticated endpoint can return, in one place.
STANDARD_ERRORS = [BAD_REQUEST, UNAUTHORIZED, FORBIDDEN, NOT_FOUND, THROTTLED, SERVER_ERROR]
