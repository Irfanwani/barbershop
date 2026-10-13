"""Rate limiting per key.

The limit belongs to the *credential*, not to the address or the person. A POS
integration sits behind a shop's office NAT, and every other caller in that
building shares its IP; limiting by IP means one integrator saturating its own
budget locks out everybody else who happens to be behind the same router.

Key requests are skipped entirely - this throttle is for keys.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class ApiKeyRateThrottle(SimpleRateThrottle):
    """One bucket per key id."""

    scope = "api_key"

    def get_cache_key(self, request, view) -> str | None:
        auth = getattr(request, "auth", None)
        key_id = getattr(auth, "pk", None)
        if key_id is None or not isinstance(getattr(auth, "prefix", None), str):
            # Not a key request. Token and session auth keep whatever limits
            # they already have.
            return None
        return f"apikey:{key_id}"

    def get_rate(self) -> str:
        return f"{settings.API_KEY_RATE_PER_MINUTE}/min"

    def allow_request(self, request, view) -> bool:
        # Tokens have their own model for this and have no prefix, so this
        # returns False - meaning "not throttled", which is what a None cache
        # key means.
        if self.get_cache_key(request, view) is None:
            return True
        return super().allow_request(request, view)
