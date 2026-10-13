"""Metrics, counted in-process and readable over HTTP.

Not Prometheus-shaped on purpose. This is a single-process Django app with a
Celery worker beside it; what is missing is *someone can see the number*, not
the exposition format. A counter nobody reads is not a metric.

So: counts in the database, percentiles kept as a bounded sample, and a
``/metrics/`` endpoint somebody can put in a dashboard or curl at 3am.

What is recorded, and why each is here:

- **Request rate and latency** — the obvious two. Percentiles rather than an
  average, because an average of 80ms hides the 8-second requests that are the
  ones people complain about.
- **Booking conversion** — quote to created, per shop. A drop here is the
  earliest sign a price change or a payment gateway is losing people.
- **No-show rate** — the thing the whole marketplace is judged on.
- **Reminder delivery** — counted by *outcome*. A reminder job that throws in a
  loop still shows as "ran"; only delivery can tell you it stopped arriving.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger("observability.metrics")

#: Bounded. An unbounded sample of every latency would be a memory leak that
#: only shows up in the process with the most traffic.
LATENCY_SAMPLE_SIZE = 2000

#: Percentiles worth looking at. p99 is the one that answers "is this slow for
# somebody" - and p50 alone hides everything.
PERCENTILES = (0.5, 0.9, 0.99)

#: In-process counters, flushed to the database periodically. A write per
#: request would be a write amplification problem on exactly the busiest
#: endpoint.
_counters: dict[tuple[str, ...], int] = defaultdict(int)
_latencies: deque[tuple[str, deque[float]]] = deque()


def reset() -> None:
    """Clear the in-process state. For tests, and for a process that has just
    been forked and must not inherit its parent's numbers."""
    _counters.clear()
    _latencies.clear()


def increment(name: str, *, by: int = 1, **labels) -> None:
    _counters[(name, *sorted(f"{k}={v}" for k, v in labels.items()))] += by


def observe_request(*, method: str, path: str, status: int, duration_ms: float) -> None:
    """Count one request and remember how long it took.

    ``path`` is normalised rather than the raw URL, so ``/bookings/BK-1234/``
    does not become a thousand distinct metric keys and then get refused.
    """
    route = normalise_path(path)
    increment("requests", method=method, path=route, status=_status_class(status))
    _record_latency(route, duration_ms)


def normalise_path(path: str) -> str:
    """Turn a concrete URL into a shape.

    Bookings, payments and API keys all have ids in the path, and an
    un-normalised counter is a memory leak with extra steps.
    """
    import re

    cleaned = re.sub(r"/(BK|PK|ORD|AC)[A-Z0-9]{4,}", "/{reference}", path)
    cleaned = re.sub(r"/\d{3,}", "/{id}", cleaned)
    # The export and API-key endpoints sit under /api/v1; the rest do not.
    return cleaned.rstrip("/") or "/"


def _status_class(status: int) -> str:
    if status < 400:
        return "2xx-3xx"
    if status < 500:
        return "4xx"
    return "5xx"


def _record_latency(route: str, duration_ms: float) -> None:
    for entry in _latencies:
        if entry[0] == route:
            entry[1].append(duration_ms)
            return
    if len(_latencies) < 500:
        _latencies.append((route, deque([duration_ms], maxlen=LATENCY_SAMPLE_SIZE)))


def observe_conversion(*, provider_id: int, quoted: bool = False, created: bool = False) -> None:
    """Quote and booking, counted against the same shop.

    Paired by shop so the ratio is meaningful: a platform-wide conversion rate
    can be steady while one shop's payment page is broken.
    """
    if quoted:
        increment("booking_quotes", provider=provider_id)
    if created:
        increment("bookings_created", provider=provider_id)


def observe_reminder(*, channel: str, outcome: str, count: int = 1) -> None:
    """One reminder delivery attempt and what came of it.

    ``outcome`` is what makes this worth recording: ``sent``, ``failed`` or
    ``skipped_no_token``. Counting "ran" tells you nothing.
    """
    increment("reminder_delivery", channel=channel, outcome=outcome, by=count)


def observe_no_show(*, provider_id: int, no_show: bool) -> None:
    increment("appointments_ended", provider=provider_id, outcome="no_show" if no_show else "other")


def snapshot() -> dict:
    """Everything counted, as a flat dict of names to values."""
    counters: dict[str, int] = defaultdict(int)
    for key, value in _counters.items():
        name, *labels = key
        counters[f"{name}{{{','.join(labels)}}}" if labels else name] += value
    return {
        "counters": dict(counters),
        "latency_ms": latency_percentiles(),
        "generated_at": timezone.now().isoformat(),
    }


def latency_percentiles() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for route, samples in _latencies:
        if not samples:
            continue
        ordered = sorted(samples)
        out[route] = {
            f"p{int(p * 100)}": round(_percentile(ordered, p), 2) for p in PERCENTILES
        } | {"samples": len(ordered)}
    return out


def _percentile(ordered: list[float], fraction: float) -> float:
    """Nearest-rank. No interpolation, because a p99 that is not a real observed
    number is a number nobody can go and look at."""
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def booking_conversion(window_days: int = 30) -> dict:
    """Quotes against bookings over a window.

    Counted from the bookings table rather than the live counters, so the number
    survives a process restart and can be asked about last month.
    """
    from bookings.models import Booking

    since = timezone.now() - timedelta(days=window_days)
    created = Booking.objects.filter(created_at__gte=since).count()
    # A quote leaves no row, so the denominator is the counter's best estimate
    # since the process started; below a threshold it is reported as unknown
    # rather than as a ratio of made-up numbers.
    quoted = sum(value for key, value in _counters.items() if key[0] == "booking_quotes")
    return {
        "window_days": window_days,
        "bookings_created": created,
        "quotes_since_start": quoted,
        "conversion": round(created / quoted, 3) if quoted >= 20 else None,
    }


def no_show_rate(window_days: int = 30) -> dict:
    from bookings.models import Booking, BookingStatus

    since = timezone.now() - timedelta(days=window_days)
    ended = Booking.objects.filter(
        created_at__gte=since,
        status__in=[BookingStatus.COMPLETED, BookingStatus.NO_SHOW],
    )
    total = ended.count()
    missed = ended.filter(status=BookingStatus.NO_SHOW).count()
    return {
        "window_days": window_days,
        "appointments_ended": total,
        "no_shows": missed,
        # None below a sample worth quoting: a rate of 100% from one appointment
        # is true and useless.
        "no_show_rate": round(missed / total, 3) if total >= 10 else None,
    }


def reminder_delivery(window_days: int = 30) -> dict:
    """Delivery outcomes, and whether they have stopped.

    The count of "sent" is the comfortable one to look at and the one that lies
    most often, because a reminder that failed every night still ran every
    night. This reports the failures next to the successes, and the alert below
    fires on the ratio.
    """
    from observability.models import DeliveryFailure

    since = timezone.now() - timedelta(days=window_days)
    outcomes: dict[str, int] = defaultdict(int)
    for key, value in _counters.items():
        if key[0] == "reminder_delivery":
            outcome = next(
                (part.split("=", 1)[1] for part in key[1:] if part.startswith("outcome=")), ""
            )
            outcomes[outcome] += value

    recent_failures = DeliveryFailure.objects.filter(created_at__gte=since).count()
    return {
        "window_days": window_days,
        "by_outcome": dict(outcomes),
        "recorded_failures": recent_failures,
        "healthy": reminder_health(outcomes, window_days),
    }


def reminder_health(outcomes: dict[str, int], window_days: int = 30) -> dict:
    """Is reminder delivery still working?

    The silent failure mode of a Celery app is not a crash - it is a job that
    runs, finds nothing, and sends nothing, while every dashboard says the job
    is green. So this is about the *ratio*, and it returns ``None`` rather than
    a verdict when there has not been enough traffic to tell.
    """
    sent = outcomes.get("sent", 0)
    failed = outcomes.get("failed", 0)
    total = sent + failed
    if total < 20:
        return {"state": "unknown", "reason": "too few deliveries to judge"}
    rate = failed / total
    if rate >= 0.2:
        return {"state": "failing", "failure_rate": round(rate, 3), "failed": failed}
    return {"state": "ok", "failure_rate": round(rate, 3), "failed": failed}
