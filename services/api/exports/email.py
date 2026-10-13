"""Sending the export.

Attaches one file per dataset rather than zipping them, because a salon opens
the file it asked for. Every attachment is named for its dataset, so a folder
of four ``export.csv`` files helps nobody.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from exports.csv import ExportFile

logger = logging.getLogger(__name__)

BRAND = "BarberShop"


def send_export(*, to: str, provider_name: str, period: str, files: list[ExportFile]) -> bool:
    """Email the export, or say clearly that it did not go.

    Returns whether it went. The caller records that on the request row, because
    an export that silently vanished leaves the person who pressed the button
    with no way to tell it failed and no way to know to ask again.
    """
    if not files:
        logger.warning("Refusing to email an export with no files to %s", to)
        return False

    try:
        body = render_to_string(
            "email/export_ready.txt",
            {
                "brand": BRAND,
                "provider_name": provider_name,
                "period": period,
                "file_names": [item.filename for item in files],
                "support_email": settings.DEFAULT_FROM_EMAIL,
            },
        )
        message = EmailMultiAlternatives(
            subject=f"Your {BRAND} export for {period}",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to],
        )
        for item in files:
            message.attach(item.filename, item.content, "text/csv")
        message.send(fail_silently=False)
    except Exception:
        logger.exception("Could not send the export to %s", to)
        return False
    return True
