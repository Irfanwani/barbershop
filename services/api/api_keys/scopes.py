"""What a key is allowed to do.

Scopes are strings rather than a bitmask so a key's permissions are readable in
the database, in the UI, and in a log line without a lookup table.

The split is coarse on purpose. A POS integration wants to *do* things; a
dashboard wants to *see* things. Anything finer than read/write invites the
question "which is this endpoint again?", and an endpoint that forgets to
declare its scope fails open - which is the wrong way round.

**Unlisted means denied.** An endpoint with no scope declared is unreachable
with a key at all, rather than reachable with any key.
"""

from __future__ import annotations

from rest_framework import permissions

READ = "read"
WRITE = "write"

ALL_SCOPES = [READ, WRITE]

SCOPE_CHOICES = [
    (READ, "Read - see this account's data"),
    (WRITE, "Write - create, change and cancel"),
]

#: Safe methods never need a scope check beyond "has any key".
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def scope_for_request(request) -> str | None:
    """The scope a method needs, or ``None`` when it needs nothing.

    ``None`` means "any authenticated caller", which is how a key with only
    ``read`` can still GET. An endpoint that wants to be key-reachable
    declares itself with :func:`key_scoped`.
    """
    from rest_framework.permissions import SAFE_METHODS as SAFE

    return None if request.method in SAFE else WRITE


class HasKeyScope(permissions.BasePermission):
    """Refuse a write from a key that only has ``read``.

    Applied on the views a key is allowed to reach. The check is on the key
    rather than on the user, because the user is authenticated by the token and
    the key is what limited them.
    """

    message = "This key does not have permission to do that."

    def has_permission(self, request, view) -> bool:
        key = getattr(request, "api_key", None)
        if key is None:
            # Not a key request. Token or session auth, which has its own
            # permission model and is not this class's business.
            return True

        needed = getattr(view, "required_scope", None)
        if needed is None:
            needed = READ if request.method in SAFE_METHODS else WRITE

        return key.has_scope(needed)


def key_scoped(scope: str | None = None):
    """Mark a view as reachable by API keys, with an optional fixed scope.

    Without this an endpoint simply is not reachable with a key: a POS
    integration must not be able to reach an endpoint nobody thought about when
    keys existed.
    """

    def decorate(view):
        view.required_scope = scope if scope is not None else "__by_method__"
        return view

    return decorate
