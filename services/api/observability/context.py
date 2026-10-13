"""The request id, and putting it on everything.

One id per request, generated at the edge, carried through the log lines, the
error tracker and the response header. The acceptance for this whole feature is
a sentence: *a failed request is findable by its request id in the error
tracker* — and that only works if the id is attached in exactly one place and
then propagated rather than re-derived at each site.

Held in a :class:`~contextvars.ContextVar`, not a thread local. Context
variables follow an ``await`` across a thread pool, which a thread local does
not; getting this wrong means async views log an empty id and every trace is
unfindable, which is the failure mode this module exists to prevent.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_request_id: ContextVar[str] = ContextVar("request_id", default="")


def new_request_id() -> str:
    """Mint one. Twelve hex characters is enough to search by and short enough
    to read out over the phone to somebody debugging a problem."""
    return uuid.uuid4().hex[:12]


def set_request_id(value: str | None = None) -> str:
    """Set it for this request and return it.

    Passing a value in is for the case where an edge already generated one — a
    load balancer, or an API gateway. Reusing theirs is what lets a trace join
    up across the systems in front of us.
    """
    request_id = (value or new_request_id()).strip()
    # Bounded, because this arrives from a header in some deployments and
    # whatever is in there ends up in log lines and an error tracker.
    request_id = request_id[:64] or new_request_id()
    _request_id.set(request_id)
    return request_id


def get_request_id() -> str:
    return _request_id.get()


def clear_request_id() -> None:
    _request_id.set("")


HEADER = "X-Request-ID"

#: The two headers a client might be using. Ours first, because that is what we
#: emit; theirs is for an edge that already minted one.
INBOUND_HEADERS = (HEADER, "X-Request-Id", "X-Correlation-ID")
