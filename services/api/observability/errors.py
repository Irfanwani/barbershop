"""Reporting an error somewhere somebody will actually look.

Sentry when a DSN is configured; a structured log line and nothing else when it
is not. The point is that **the request id is on the report either way**, so the
acceptance - *a failed request is findable by its request id* - does not depend
on somebody having bought an error tracker.

Never raises. A tracker that is down, slow, or misconfigured must not turn a
handled 400 into a 500, which is the one job an error reporter must not have.
"""

from __future__ import annotations

import logging

from django.conf import settings

from observability.context import get_request_id

logger = logging.getLogger("observability.errors")

_initialised = False


def _sentry():
    global _initialised
    if _initialised:
        return None

    _initialised = True
    if not getattr(settings, "SENTRY_DSN", ""):
        return None

    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            integrations=[DjangoIntegration(), CeleryIntegration()],
            environment=getattr(settings, "SENTRY_ENVIRONMENT", ""),
            # Enough of the traceback to see what happened, not the whole local
            # source tree pasted into a third party.
            traces_sample_rate=0,
            send_default_pii=False,
        )
        return sentry_sdk
    except Exception:
        logger.exception("Could not initialise error tracking")
        return None


def report(exc: Exception, *, context: dict | None = None) -> None:
    """Report one error, tagged with the request id.

    Always logs. The tracker is the place to *search*; the log is the place to
    *see* what happened, and a deployment with no tracker should still produce
    something to read.
    """
    request_id = get_request_id()

    logger.error(
        "Unhandled error",
        extra={
            "request_id": request_id,
            "exception_type": type(exc).__name__,
            **(context or {}),
        },
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    sentry = _sentry()
    if sentry is None:
        return

    try:
        with sentry.push_scope() as scope:
            if request_id:
                # The tag, not just the message: Sentry's search is by tag, and
                # "find the event whose request id is this" is the whole
                # acceptance criterion.
                scope.set_tag("request_id", request_id)
            for key, value in (context or {}).items():
                scope.set_extra(key, value)
            sentry.capture_exception(exc)
    except Exception:
        # A tracker that throws while reporting is worse than no tracker.
        logger.exception("Could not report an error to the tracker")
