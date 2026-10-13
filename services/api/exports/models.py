"""A record of an export somebody asked for.

The file itself is not kept. That is deliberate: an export is a copy of data the
shop already has access to through the product, it goes out by email, and a
downloadable file sitting in storage is a file that gets shared, then copied,
then found in a breach a year later.

What is kept is the row: who asked, for what period, with which datasets, and
whether it arrived. Without it, "the export never came" is unactionable - the
person who pressed the button has no way to find out it failed and no way to
ask again without pressing it again and hoping.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import TimeStampedModel


class ExportStatus(models.TextChoices):
    #: Queued for the worker. The only state a request is ever left in.
    QUEUED = "queued", "Queued"
    #: Built and emailed.
    SENT = "sent", "Sent"
    #: It could not be sent. Kept, because a failure nobody is told about is a
    #: failure that gets repeated.
    FAILED = "failed", "Failed"


class ExportRequest(TimeStampedModel):
    """One request for a spreadsheet, and what became of it."""

    provider = models.ForeignKey(
        "providers.ProviderProfile", on_delete=models.CASCADE, related_name="export_requests"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="export_requests"
    )

    from_date = models.DateField()
    to_date = models.DateField()

    #: Which datasets. A list so a request can grow without a migration.
    datasets = models.JSONField(default=list)

    status = models.CharField(
        max_length=16, choices=ExportStatus.choices, default=ExportStatus.QUEUED
    )
    row_count = models.PositiveIntegerField(default=0)
    failure_reason = models.CharField(max_length=300, blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "exports_exportrequest"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["provider", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.provider} {self.from_date}..{self.to_date} ({self.status})"

    @property
    def filename_base(self) -> str:
        return f"barbershop-{self.provider_id}-{self.from_date}-{self.to_date}"
