"""What is worth remembering after the process restarts.

Counters are in memory and reset on every restart, which is fine for "how many
requests in the last minute" and useless for "was this working yesterday". The
two things worth keeping are the ones a human asks about after something has
already gone wrong:

- **A failure somebody will ask to see later.** A reminder that failed at 03:00
  is gone from memory by the time anybody looks.
- **An alert that has fired**, so an alert storm is visible as one incident
  rather than a hundred notifications.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class DeliveryFailure(models.Model):
    """One thing that failed to be delivered.

    Push, WhatsApp, email - anything where a failure is invisible to the person
    it was meant to reach. The user-visible symptom of all of them is the same:
    they do not hear about their appointment.
    """

    class Channel(models.TextChoices):
        PUSH = "push", "Push"
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "Email"

    channel = models.CharField(max_length=16, choices=Channel.choices)
    reason = models.CharField(max_length=300, blank=True, default="")
    reference = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="A booking reference or similar, so the row can be acted on.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "observability_deliveryfailure"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["channel", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.channel} delivery failed: {self.reason[:40]}"


class Alert(models.Model):
    """Something worth waking somebody for.

    Recorded rather than only sent, so "did we get paged about this?" has an
    answer and a repeated failure does not produce a repeated page.
    """

    class Kind(models.TextChoices):
        REMINDER_DELIVERY = "reminder_delivery", "Reminder delivery failing"

    kind = models.CharField(max_length=32, choices=Kind.choices)
    severity = models.CharField(max_length=8, default="high")
    message = models.CharField(max_length=300)
    details = models.JSONField(default=dict, blank=True)
    raised_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "observability_alert"
        ordering = ["-raised_at"]
        constraints = [
            # One live alert per kind. A failing thing produces one page, not one
            # per five minutes for six hours.
            models.UniqueConstraint(
                fields=["kind"],
                condition=models.Q(resolved_at__isnull=True),
                name="observability_one_live_alert_per_kind",
            )
        ]

    def __str__(self) -> str:
        return f"{self.kind}: {self.message[:50]}"

    @property
    def is_live(self) -> bool:
        return self.resolved_at is None or self.resolved_at > timezone.now()
