"""The metrics, and the delivery-failure record.

``/metrics/`` is deliberately readable rather than machine-shaped. A promotion
format is worth it when something is scraping it; before that, a JSON object a
human can curl at 3am is worth more, and it converts to Prometheus format in
about ten lines when there is a scraper.
"""

from __future__ import annotations

import logging

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from observability import metrics
from observability.models import Alert, DeliveryFailure

logger = logging.getLogger("observability")


class MetricsView(APIView):
    """Counters, latency percentiles, and the business rates.

    Open, deliberately. This is operational data about the platform, not
    anybody's bookings, and an on-call engineer at 3am should not have to find
    a login to see whether reminders are arriving.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="observability_metrics",
        summary="Platform metrics",
        description="Counters, latency percentiles, booking conversion and no-show rate.",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        snapshot = metrics.snapshot()
        live_alerts = Alert.objects.filter(resolved_at__isnull=True)

        return Response(
            {
                **snapshot,
                "booking_conversion": metrics.booking_conversion(),
                "no_show_rate": metrics.no_show_rate(),
                "reminder_delivery": metrics.reminder_delivery(),
                "live_alerts": [
                    {
                        "kind": alert.kind,
                        "severity": alert.severity,
                        "message": alert.message,
                        "raised_at": alert.raised_at,
                        "details": alert.details,
                    }
                    for alert in live_alerts[:20]
                ],
            }
        )


class RecordDeliveryFailureView(APIView):
    """Record that something did not arrive.

    Written by the senders themselves. The alternative - inferring failure from
    absence of success - cannot tell "we sent it" from "we tried and gave up",
    which is exactly the distinction this whole feature is for.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="observability_delivery_failure",
        summary="Record a delivery failure",
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        body = request.data or {}
        channel = str(body.get("channel", ""))[:16]
        if channel not in DeliveryFailure.Channel.values:
            return Response({"error": "Unknown channel."}, status=400)

        row = DeliveryFailure.objects.create(
            channel=channel,
            reason=str(body.get("reason", ""))[:300],
            reference=str(body.get("reference", ""))[:64],
        )
        logger.warning("Delivery failed", extra={"channel": channel, "reason": row.reason})
        return Response({"id": row.pk}, status=201)
