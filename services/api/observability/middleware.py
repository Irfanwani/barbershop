"""The middleware that starts and ends a trace.

Runs outside Django's exception handling on purpose: it sets the id *before*
anything can fail, and it times the request and records the outcome on the way
out whether the view returned 200, 400 or exploded.

Timing is measured around the whole thing rather than inside the view, so a
request that dies during body parsing is still counted. A metric that only
records requests that finished is a metric that makes an outage look like a
lull.
"""

from __future__ import annotations

import logging
import time

from django.http import HttpResponse

from observability import metrics
from observability.context import (
    HEADER,
    INBOUND_HEADERS,
    clear_request_id,
    set_request_id,
)

logger = logging.getLogger("observability.request")


def inbound_request_id(request) -> str | None:
    """Whatever id arrived from an edge, if any.

    Normalised to the header name we emit, so a caller who retried a request
    across a retrying gateway can search once.
    """
    meta_key = "HTTP_X_REQUEST_ID"
    for header in INBOUND_HEADERS:
        value = request.headers.get(header) or request.META.get(
            f"HTTP_{header.upper().replace('-', '_')}"
        )
        if value:
            return value
    return request.META.get(meta_key)


class RequestIdMiddleware:
    """Attach a request id to everything, and time what happened."""

    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request) -> HttpResponse:
        request_id = set_request_id(inbound_request_id(request))
        request.request_id = request_id
        started = time.perf_counter()

        try:
            response = self.get_response(request)
        except Exception:
            # Recorded here as well as by the exception handler: this is the
            # only place that knows the status code is a 500, and a 500 nobody
            # counted is a 500 nobody is alerted about.
            duration_ms = (time.perf_counter() - started) * 1000
            metrics.observe_request(
                method=request.method,
                path=request.path,
                status=500,
                duration_ms=duration_ms,
            )
            logger.exception("Unhandled error while handling %s %s", request.method, request.path)
            clear_request_id()
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        metrics.observe_request(
            method=request.method,
            path=request.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        response[HEADER] = request_id
        clear_request_id()
        return response
