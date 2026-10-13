"""Building and sending exports.

A year of bookings is not a synchronous response. The request records what was
asked for and returns immediately; the worker builds the files and emails them.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from exports import csv, email
from exports.models import ExportRequest, ExportStatus

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True, bind=True, max_retries=3)
def run_export(self, request_id: int) -> None:
    """Build every dataset for one request and email it.

    Retried on a transient failure, because the two things that can go wrong
    here - an SMTP blip and a database hiccup - are both worth trying again.
    A refusal (too many rows, no such shop) is not retried; there is no point
    trying a month-long export three times to find out it is too large.
    """
    request_row = ExportRequest.objects.filter(pk=request_id).first()
    if request_row is None:
        logger.info("Export %s vanished before it ran", request_id)
        return
    if request_row.status == ExportStatus.SENT:
        # The task can be redelivered. Sending twice is the one thing that must
        # never happen here.
        logger.info("Export %s already sent; not sending again", request_id)
        return

    provider = request_row.provider
    try:
        files = csv.build(
            provider, request_row.from_date, request_row.to_date, request_row.datasets
        )
    except csv.ExportTooLarge as refused:
        _fail(request_row, str(refused))
        return
    except Exception as exc:
        logger.exception("Could not build export %s", request_id)
        _fail(request_row, str(exc)[:300])
        raise self.retry(exc=exc, countdown=60) from exc

    to = request_row.requested_by.email
    sent = email.send_export(
        to=to,
        provider_name=provider.display_name,
        period=f"{request_row.from_date} to {request_row.to_date}",
        files=files,
    )

    if sent:
        request_row.status = ExportStatus.SENT
        request_row.row_count = sum(item.row_count for item in files)
        request_row.sent_at = timezone.now()
        request_row.save(update_fields=["status", "row_count", "sent_at", "updated_at"])
        logger.info("Export %s sent (%s rows)", request_id, request_row.row_count)
    else:
        # Not retried. A refused email is usually a bad address, and retrying
        # sends it to the same wrong place three times.
        _fail(request_row, "The email could not be sent.")


def _fail(request_row: ExportRequest, reason: str) -> None:
    request_row.status = ExportStatus.FAILED
    request_row.failure_reason = reason[:300]
    request_row.save(update_fields=["status", "failure_reason", "updated_at"])
    logger.warning("Export %s failed: %s", request_row.pk, reason)
