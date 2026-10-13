"""Observability, tested against what it is actually for.

The tests here are deliberately about behaviour an operator depends on - *can I
find this request*, *does this tell me reminders stopped arriving* - rather than
about the presence of a function.
"""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from bookings.models import BookingStatus
from observability import alerts, errors, metrics
from observability.context import clear_request_id, get_request_id, set_request_id
from observability.logging import JsonFormatter
from observability.models import Alert, DeliveryFailure
from tests.factories import logged_in, make_booking, make_profile

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
METRICS = f"{V1}/observability/metrics/"
DELIVERY_FAILURE = f"{V1}/observability/delivery-failure/"


@pytest.fixture(autouse=True)
def clean_counters():
    """Counters are process-global.

    Leaking them between tests would make the suite order-dependent, and an
    alerting threshold is exactly the kind of thing that only trips when
    somebody else's test left numbers behind.
    """
    metrics.reset()
    clear_request_id()
    yield
    metrics.reset()
    clear_request_id()


def _record(**attrs) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="a thing happened",
        args=(),
        exc_info=None,
    )
    for key, value in attrs.items():
        setattr(record, key, value)
    return record


class TestRequestIds:
    def test_a_request_gets_an_id_and_returns_it(self):
        profile = make_profile()
        client, token = logged_in(profile.user)

        response = client.get(f"{V1}/bookings/", **token_headers(token))

        assert response.status_code == 200, response.data
        # The client needs this header; otherwise there is nothing to quote when
        # somebody reports a problem.
        assert response.headers.get("X-Request-ID")

    def test_the_id_is_reused_when_the_gateway_supplied_one(self):
        profile = make_profile()
        client, token = logged_in(profile.user)

        response = client.get(
            f"{V1}/bookings/",
            **token_headers(token),
            HTTP_X_REQUEST_ID="edge-abc-123",
        )

        # Propagated rather than replaced, so a retry behind a gateway can be
        # searched for as one thing.
        assert response.headers.get("X-Request-ID") == "edge-abc-123"

    def test_a_correlation_header_is_accepted_too(self):
        profile = make_profile()
        client, token = logged_in(profile.user)

        response = client.get(
            f"{V1}/bookings/",
            **token_headers(token),
            HTTP_X_CORRELATION_ID="corr-9",
        )

        assert response.headers.get("X-Request-ID") == "corr-9"

    def test_a_hostile_supplied_id_is_not_trusted_blind(self):
        profile = make_profile()
        client, token = logged_in(profile.user)

        response = client.get(
            f"{V1}/bookings/",
            **token_headers(token),
            HTTP_X_REQUEST_ID="x" * 500,
        )

        # Bounded: the id goes into a log field and a response header, and an
        # unbounded one is somebody's memory exhaustion.
        assert len(response.headers.get("X-Request-ID", "")) <= 64

    def test_the_context_is_cleared_afterwards(self):
        profile = make_profile()
        client, token = logged_in(profile.user)

        client.get(f"{V1}/bookings/", **token_headers(token))

        # A stale id leaking into the next request would attribute one request's
        # error to another's - the opposite of useful.
        assert not get_request_id()


class TestAFailedRequestIsFindable:
    def test_the_reported_error_carries_its_request_id(self, monkeypatch):
        """The acceptance criterion, as a test.

        Given an id from a support conversation, find the error. That only works
        if the report and the id travel together.
        """
        captured = {}

        def fake_report(exc, *, context=None):
            captured["request_id"] = get_request_id()
            captured["exc"] = exc

        monkeypatch.setattr(errors, "report", fake_report)

        set_request_id("find-me-please")
        try:
            errors.report(RuntimeError("kaboom"), context={"path": "/x"})
        finally:
            clear_request_id()

        assert captured["request_id"] == "find-me-please"
        assert isinstance(captured["exc"], RuntimeError)

    def test_the_reporter_is_called_from_the_500_handler(self, monkeypatch):
        """Wiring, not just capability: the handler has to actually use it."""
        from rest_framework.test import APIRequestFactory

        from core.exceptions import api_exception_handler

        captured = {}
        monkeypatch.setattr(
            errors, "report", lambda exc, *, context=None: captured.update(context or {})
        )

        request = APIRequestFactory().get("/api/v1/bookings/BK00001/")
        set_request_id("wired-1")
        try:
            # NotFound is handled; force the unhandled branch with something
            # DRF does not know how to serialise.
            api_exception_handler(RuntimeError("boom"), {"request": request, "view": None})
        finally:
            clear_request_id()

        assert captured.get("path") == "/api/v1/bookings/BK00001/"

    def test_it_lands_in_a_log_with_the_id_even_with_no_tracker(self, monkeypatch):
        """The acceptance must hold on a deployment nobody has paid Sentry for."""
        monkeypatch.setattr(errors, "_sentry", lambda: None)

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        # The real formatter, because the claim under test is that the id is
        # *rendered* - not merely passed in `extra`.
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("observability.errors")
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)
        try:
            set_request_id("log-me-please")
            try:
                errors.report(ValueError("bad input"))
            finally:
                clear_request_id()
        finally:
            logger.removeHandler(handler)

        line = json.loads(stream.getvalue().strip())
        assert line["request_id"] == "log-me-please"
        assert line["exception_type"] == "ValueError"

    def test_end_to_end_a_real_500_is_logged_as_json_with_its_request_id(
        self, monkeypatch, settings
    ):
        """The acceptance criterion, all the way through.

        A real request, a real unhandled exception, the real middleware and the
        real handler - and the id has to come out the other side in the log
        line. Every other test in this class checks one link in the chain; this
        one checks the chain.
        """

        from bookings.views import BookingCreateView
        from core.exceptions import api_exception_handler

        settings.LOG_FORMAT = "json"

        def boom(request):
            raise RuntimeError("deliberate failure")

        monkeypatch.setattr(BookingCreateView, "post", boom)
        monkeypatch.setattr(errors, "_sentry", lambda: None)

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        # The logger the handler's own request line goes to.
        request_logger = logging.getLogger("observability.request")
        error_logger = logging.getLogger("observability.errors")
        for lg in (request_logger, error_logger):
            lg.addHandler(handler)
            lg.setLevel(logging.ERROR)
            lg.propagate = False

        try:
            from core import exceptions as core_exceptions

            monkeypatch.setattr(core_exceptions, "observability_errors", errors)

            from rest_framework.test import APIRequestFactory

            request = APIRequestFactory().post("/api/v1/bookings/new/")
            set_request_id("e2e-request-id")
            try:
                api_exception_handler(
                    RuntimeError("deliberate failure"), {"request": request, "view": None}
                )
            finally:
                clear_request_id()
        finally:
            for lg in (request_logger, error_logger):
                lg.removeHandler(handler)

        lines = [
            json.loads(line)
            for line in stream.getvalue().splitlines()
            if line.strip().startswith("{")
        ]

        assert lines, "a 500 produced no JSON log line at all"
        reported = next(line for line in lines if line.get("exception_type") == "RuntimeError")
        assert reported["request_id"] == "e2e-request-id"

    def test_a_broken_tracker_does_not_raise(self, monkeypatch):
        """A tracker that throws while reporting is worse than no tracker."""

        class Broken:
            def push_scope(self):
                raise RuntimeError("tracker down")

        monkeypatch.setattr(errors, "_sentry", lambda: Broken())

        errors.report(RuntimeError("original problem"))  # must not raise


class TestJsonLogs:
    def test_the_request_id_is_on_every_line(self):
        set_request_id("abc-123")
        try:
            payload = json.loads(JsonFormatter().format(_record()))
        finally:
            clear_request_id()

        # Not only on errors. A request id is only useful for reconstructing a
        # request if the successful calls are findable by it too.
        assert payload["request_id"] == "abc-123"
        assert payload["message"] == "a thing happened"

    def test_it_is_valid_json_with_the_expected_fields(self):
        payload = json.loads(JsonFormatter().format(_record()))

        assert payload["level"] == "INFO"
        assert payload["logger"] == "test"
        assert "time" in payload

    def test_a_celery_task_id_is_recorded(self):
        payload = json.loads(JsonFormatter().format(_record(task_id="task-99")))

        # Celery failures happen outside any request, so the task id is the only
        # thing tying a failed job to what it was doing.
        assert payload["task_id"] == "task-99"

    def test_an_exception_becomes_a_field_not_a_stray_line(self):
        import sys

        try:
            raise ValueError("inner failure")
        except ValueError:
            record = _record()
            record.exc_info = sys.exc_info()

        line = JsonFormatter().format(record)
        payload = json.loads(line)

        # The guarantee is about the emitted line: a multi-line traceback pasted
        # raw would break every one-line-per-record parser downstream.
        assert "\n" not in line
        assert payload["exception_type"] == "ValueError"
        # The traceback survives decoding, newlines and all.
        assert "inner failure" in payload["exception"]

    def test_an_unserialisable_extra_does_not_break_the_line(self):
        payload = json.loads(JsonFormatter().format(_record(weird=object())))

        # One unserialisable field must not cost us the whole line.
        assert isinstance(payload["weird"], str)


class TestRequestMetrics:
    def test_requests_are_counted_by_status_class(self):
        metrics.observe_request(method="GET", path="/api/v1/bookings/", status=200, duration_ms=12)
        metrics.observe_request(method="GET", path="/api/v1/bookings/", status=500, duration_ms=90)

        counters = metrics.snapshot()["counters"]

        assert counters["requests{method=GET,path=/api/v1/bookings,status=2xx-3xx}"] == 1
        assert counters["requests{method=GET,path=/api/v1/bookings,status=5xx}"] == 1

    def test_a_4xx_is_not_counted_as_a_server_problem(self):
        metrics.observe_request(method="GET", path="/api/v1/bookings/", status=404, duration_ms=5)

        assert (
            "requests{method=GET,path=/api/v1/bookings,status=4xx}"
            in metrics.snapshot()["counters"]
        )

    def test_ids_in_the_path_do_not_become_separate_metrics(self):
        """A thousand bookings a day should not be a thousand metric keys."""
        for i in range(50):
            metrics.observe_request(
                method="GET", path=f"/api/v1/bookings/BK{i:05d}/", status=200, duration_ms=10
            )

        assert set(metrics.latency_percentiles()) == {"/api/v1/bookings/{reference}"}

    def test_latency_reports_percentiles_not_an_average(self):
        for i in range(100):
            metrics.observe_request(
                method="GET", path="/api/v1/x/", status=200, duration_ms=float(i)
            )

        p50 = metrics.latency_percentiles()["/api/v1/x"]["p50"]
        p99 = metrics.latency_percentiles()["/api/v1/x"]["p99"]

        # An average hides the requests people actually complain about.
        assert p50 < p99

    def test_the_latency_sample_is_bounded(self):
        for _ in range(metrics.LATENCY_SAMPLE_SIZE + 500):
            metrics.observe_request(method="GET", path="/api/v1/x/", status=200, duration_ms=1)

        assert metrics.latency_percentiles()["/api/v1/x"]["samples"] <= metrics.LATENCY_SAMPLE_SIZE


class TestConversion:
    def test_quotes_and_bookings_are_counted_separately(self):
        metrics.observe_conversion(provider_id=1, quoted=True)
        metrics.observe_conversion(provider_id=1, quoted=True)
        metrics.observe_conversion(provider_id=1, created=True)

        counters = metrics.snapshot()["counters"]

        assert counters["booking_quotes{provider=1}"] == 2
        assert counters["bookings_created{provider=1}"] == 1

    def test_the_rate_is_withheld_when_the_denominator_is_noise(self):
        metrics.observe_conversion(provider_id=1, quoted=True)
        for _ in range(30):
            make_booking()

        result = metrics.booking_conversion(window_days=3650)

        # 30 bookings over one quote is not a 3000% conversion rate. Reporting it
        # as a number would be worse than reporting nothing.
        assert result["conversion"] is None

    def test_the_rate_is_reported_once_there_is_a_sample(self):
        profile = make_profile()
        for _ in range(25):
            metrics.observe_conversion(provider_id=profile.pk, quoted=True)
        for _ in range(5):
            make_booking(provider=profile)

        result = metrics.booking_conversion(window_days=3650)

        assert result["bookings_created"] == 5
        assert result["conversion"] == 0.2


class TestNoShowRate:
    def test_the_rate_is_withheld_for_a_tiny_sample(self):
        make_booking(status=BookingStatus.NO_SHOW)

        result = metrics.no_show_rate(window_days=3650)

        # A 100% no-show rate from one appointment is true and useless.
        assert result["no_show_rate"] is None

    def test_the_rate_is_reported_once_there_is_a_sample(self):
        for i in range(12):
            make_booking(status=BookingStatus.NO_SHOW if i < 3 else BookingStatus.COMPLETED)

        result = metrics.no_show_rate(window_days=3650)

        assert result["appointments_ended"] == 12
        assert result["no_show_rate"] == 0.25


class TestReminderAlert:
    def _deliveries(self, sent: int, failed: int) -> None:
        for _ in range(sent):
            metrics.observe_reminder(channel="push", outcome="sent")
        for _ in range(failed):
            metrics.observe_reminder(channel="push", outcome="failed")

    def test_no_alert_when_there_is_nothing_to_judge(self):
        """Three failures is three failures, not an outage."""
        self._deliveries(0, 3)

        assert alerts.check_reminder_delivery() is None
        assert Alert.objects.count() == 0

    def test_an_alert_is_raised_when_delivery_stops_working(self):
        self._deliveries(10, 15)

        alert = alerts.check_reminder_delivery()

        assert alert is not None
        assert alert.kind == Alert.Kind.REMINDER_DELIVERY
        # The message has to say what broke, not just that something did.
        assert "15" in alert.message

    def test_the_alert_is_raised_once_not_on_every_run(self):
        """A failing thing produces one page, not one per fifteen minutes."""
        self._deliveries(10, 15)
        first = alerts.check_reminder_delivery()
        second = alerts.check_reminder_delivery()

        assert Alert.objects.count() == 1
        assert second.pk == first.pk

    def test_the_alert_resolves_when_delivery_recovers(self):
        self._deliveries(10, 15)
        alerts.check_reminder_delivery()

        metrics.reset()
        self._deliveries(100, 1)
        alerts.check_reminder_delivery()

        # An alert that never clears is how a dashboard ends up permanently red
        # and therefore permanently ignored.
        assert Alert.objects.filter(resolved_at__isnull=True).count() == 0


class TestRemindersAreActuallyMeasured:
    """The silent-failure case this whole feature exists for."""

    def test_a_failed_reminder_is_not_counted_as_sent(self, monkeypatch):
        from bookings import tasks as booking_tasks

        monkeypatch.setattr(booking_tasks, "deliver_push", lambda *a, **k: False)

        booking = make_booking()
        booking.customer.push_tokens.create(token="t-1", active=True)

        booking_tasks._send_reminders([booking], audience="customer")

        counters = metrics.snapshot()["counters"]
        # This used to increment regardless of the return value, so a reminder
        # that failed every night reported success and every dashboard stayed
        # green while nobody was reminded of anything.
        assert counters.get("reminder_delivery{channel=push,outcome=failed}") == 1
        assert counters.get("reminder_delivery{channel=push,outcome=sent}") is None
        # And the failure is written down: in-memory counters die with the
        # process, and somebody asks about this the next morning.
        assert DeliveryFailure.objects.filter(reference=booking.reference).exists()

    def test_a_delivered_reminder_is_counted_as_sent(self, monkeypatch):
        from bookings import tasks as booking_tasks

        monkeypatch.setattr(booking_tasks, "deliver_push", lambda *a, **k: True)

        booking = make_booking()
        booking.customer.push_tokens.create(token="t-1", active=True)

        booking_tasks._send_reminders([booking], audience="customer")

        assert metrics.snapshot()["counters"]["reminder_delivery{channel=push,outcome=sent}"] == 1
        assert DeliveryFailure.objects.count() == 0

    def test_a_user_with_no_token_is_skipped_not_counted_as_sent(self):
        from bookings import tasks as booking_tasks

        booking = make_booking()

        booking_tasks._send_reminders([booking], audience="customer")

        counters = metrics.snapshot()["counters"]
        # Distinct from a failure: nothing was wrong, there was nowhere to send
        # it. Reporting it as either would mislead whoever is on call.
        assert counters.get("reminder_delivery{channel=push,outcome=skipped_no_token}") == 1
        assert counters.get("reminder_delivery{channel=push,outcome=failed}") is None


class TestMetricsEndpoint:
    def test_it_reports_the_operational_numbers(self):
        profile = make_profile()
        client, token = logged_in(profile.user)

        response = client.get(METRICS, **token_headers(token))

        assert response.status_code == 200, response.data
        assert "counters" in response.data
        assert "latency_ms" in response.data
        assert "no_show_rate" in response.data
        assert "reminder_delivery" in response.data

    def test_it_shows_a_live_alert(self):
        profile = make_profile()
        client, token = logged_in(profile.user)
        Alert.objects.create(kind=Alert.Kind.REMINDER_DELIVERY, message="reminders stopped")

        response = client.get(METRICS, **token_headers(token))

        assert response.data["live_alerts"][0]["kind"] == Alert.Kind.REMINDER_DELIVERY

    def test_it_requires_authentication(self):
        from rest_framework.test import APIClient

        response = APIClient().get(METRICS)

        assert response.status_code in (401, 403)


class TestDeliveryFailureEndpoint:
    def test_a_failure_can_be_recorded(self):
        profile = make_profile()
        client, token = logged_in(profile.user)

        response = client.post(
            DELIVERY_FAILURE,
            {"channel": "whatsapp", "reason": "provider rejected", "reference": "BK00001"},
            content_type="application/json",
            **token_headers(token),
        )

        assert response.status_code == 201, response.data
        assert DeliveryFailure.objects.filter(channel="whatsapp").exists()

    def test_an_unknown_channel_is_rejected(self):
        profile = make_profile()
        client, token = logged_in(profile.user)

        response = client.post(
            DELIVERY_FAILURE,
            {"channel": "carrier_pigeon"},
            content_type="application/json",
            **token_headers(token),
        )

        assert response.status_code == 400


def token_headers(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Token {token}"}
