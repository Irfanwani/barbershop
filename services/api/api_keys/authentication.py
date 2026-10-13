"""Authenticating a request by API key.

Presented as ``Authorization: ApiKey <prefix>.<secret>``. The prefix is an
indexed lookup so the candidate row is fetched in one query, and the secret is
compared against the stored hash.

Three properties this is built for:

- **Revocation is immediate.** The lookup happens per request against live
  rows. A revoked key is refused on its very next call, not when a cache
  expires.
- **A wrong key is a 401, not a 403.** It is a failure to identify yourself,
  and the same error is given for an unknown prefix and a wrong secret so the
  response does not confirm which keys exist.
- **Usage is recorded.** A key nobody has used for a year is a key somebody
  should revoke, but only if the platform can tell.
"""

from __future__ import annotations

import logging

from rest_framework import authentication, exceptions

from api_keys.models import ApiKey

logger = logging.getLogger(__name__)

HEADER = "HTTP_AUTHORIZATION"
SCHEME = "apikey"


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """Reads an ``Authorization: ApiKey <key>`` header."""

    keyword = SCHEME

    def authenticate(self, request):
        header = request.META.get(HEADER, "")
        if not header:
            return None

        parts = header.split()
        if len(parts) != 2 or parts[0].lower() != self.keyword:
            # Some other scheme. Not ours, and not our problem.
            return None

        presented = parts[1]
        prefix, _, _secret = presented.partition(".")
        if not prefix:
            raise exceptions.AuthenticationFailed("That API key is not valid.")

        candidate = (
            ApiKey.objects.select_related("user").filter(prefix=prefix, is_active=True).first()
        )

        # The same message for "no such key" and "wrong secret", so this cannot
        # be used to discover which keys exist.
        if candidate is None or not candidate.matches(presented):
            logger.info("Rejected an API key with prefix %s", prefix)
            raise exceptions.AuthenticationFailed("That API key is not valid.")

        if candidate.is_expired:
            raise exceptions.AuthenticationFailed("That API key has expired.")

        view = (request.parser_context or {}).get("view")
        if view is None or getattr(view, "required_scope", None) is None:
            # Fail closed. An endpoint nobody marked as key-reachable is not
            # reachable with a key, rather than reachable with any key - the
            # difference is one forgotten decorator versus a hole somebody finds
            # by reading the URL list.
            logger.info(
                "Refused an API key on an endpoint that does not accept keys: %s",
                request.path,
            )
            raise exceptions.PermissionDenied("This endpoint cannot be reached with an API key.")

        candidate.note_used()
        # DRF sets ``request.user`` and ``request.auth``. The auth object is the
        # key itself; ``api_key`` is also set explicitly because permissions
        # should not have to guess whether auth is a key or a token by type.
        request.api_key = candidate
        return candidate.user, candidate

    def authenticate_header(self, request) -> str:
        return 'ApiKey realm="api"'
