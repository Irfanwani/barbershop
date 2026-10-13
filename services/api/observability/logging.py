"""JSON logs, because a grep is not an error tracker.

One JSON object per line, with the request id on every line produced while
handling a request. The reason for JSON rather than the human-readable default:
the fields have to be *queryable*. "Every 500 on /payments/verify in the last
hour" is a query against a field, not a regex somebody has to invent during an
incident.

The context fields live in a :class:`~contextvars.ContextVar` rather than being
passed to a ``LoggerAdapter``. An adapter only decorates its own logger; a
``logger.exception`` three modules away would carry none of it, which is exactly
the line somebody wants to find.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from observability.context import get_request_id

#: ``None`` rather than ``{}``: a ContextVar default is stored once and shared,
#: so a mutable default is a dict every caller could reach into.
_extra: ContextVar[dict | None] = ContextVar("log_extra", default=None)


@contextmanager
def context(**fields):
    """Attach fields to every log line inside the block.

    Used to say what a line was *about* — the booking reference, the shop — so
    a search for one customer's problem is a field match rather than a regex.
    """
    token = _extra.set({**(_extra.get() or {}), **fields})
    try:
        yield
    finally:
        _extra.reset(token)


class JsonFormatter(logging.Formatter):
    """Render a record as one line of JSON."""

    RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()) | {
        "message",
        "asctime",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": datetime.now(UTC).isoformat(),
        }

        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id

        # Celery tasks run outside a request, but they are the ones that fail
        # silently, so a task id is worth having.
        task_id = getattr(record, "task_id", None)
        if task_id:
            payload["task_id"] = task_id

        payload.update(_extra.get() or {})

        for key, value in record.__dict__.items():
            if key in self.RESERVED or key.startswith("_") or key in payload:
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value

        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = self.formatException(record.exc_info)
            payload["exception_type"] = record.exc_info[0].__name__

        return json.dumps(payload, default=str)
