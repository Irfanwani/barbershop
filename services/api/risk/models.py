"""What a customer's record looks like before they sit down.

The category sells this as "no-show intelligence". What it actually is, is a
small amount of arithmetic plus a lot of judgement about what to do with it,
and the judgement is where it goes wrong.

Two rules run through this module:

- **The score is advisory.** It recommends; it does not enforce. A shop that
  wants a deposit can set one for everybody. A score that quietly raised a
  customer's price without anybody being told is the kind of thing that ends
  with a chargeback and a bad review.
- **Everything is derived from bookings, not stored as a running total.** The
  same rule as the money ledger and the points ledger: a number that has to be
  kept up to date is a number that will be wrong. Recomputing is cheap at this
  volume, and being wrong here means denying somebody an appointment they had
  every right to.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel


class RiskFlag(TimeStampedModel):
    """Something a provider or the platform has flagged about a customer.

    Separate from the score on purpose. A score is arithmetic over bookings and
    changes by itself; a flag is a judgement somebody made, with a reason, and
    it does not decay because the customer had a good month.
    """

    class Kind(models.TextChoices):
        #: Booked and cancelled repeatedly, lately. Often legitimate - a diary
        #: clash - which is exactly why it is a flag and not a ban.
        SERIAL_CANCELLER = "serial_canceller", "Books and cancels repeatedly"
        #: Did not turn up more than once.
        REPEAT_NO_SHOW = "repeat_no_show", "Repeated no-shows"
        #: Text that looks like an attempt to get an appointment off-platform.
        SUSPICIOUS_NOTES = "suspicious_notes", "Suspicious booking notes"

    class Severity(models.TextChoices):
        #: Worth a look. Do not change how this customer is treated.
        LOW = "low", "Low"
        #: Worth a deposit.
        MEDIUM = "medium", "Medium"
        #: Worth refusing, if the shop chooses to.
        HIGH = "high", "High"

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="risk_flags"
    )
    provider = models.ForeignKey(
        "providers.ProviderProfile",
        on_delete=models.CASCADE,
        related_name="risk_flags",
        null=True,
        blank=True,
        help_text="Null for a platform-wide flag rather than one shop's grudge.",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    severity = models.CharField(max_length=8, choices=Severity.choices, default=Severity.LOW)
    reason = models.CharField(max_length=200)

    #: Set when somebody clears it by hand. Without this a flag that was once
    #: true is true forever, and a customer cannot move past a bad month.
    cleared_at = models.DateTimeField(null=True, blank=True)
    cleared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cleared_risk_flags",
    )

    class Meta:
        db_table = "risk_riskflag"
        ordering = ["-created_at"]
        constraints = [
            # One live flag of each kind per customer per shop. A task that runs
            # twice must not double up on somebody who is already flagged.
            models.UniqueConstraint(
                fields=["customer", "provider", "kind"],
                condition=models.Q(cleared_at__isnull=True),
                name="risk_one_live_flag_per_kind",
            )
        ]
        indexes = [models.Index(fields=["customer", "cleared_at"])]

    def __str__(self) -> str:
        return f"{self.kind} ({self.severity})"

    @property
    def is_live(self) -> bool:
        return self.cleared_at is None


class CustomerRisk(TimeStampedModel):
    """The computed picture. A cache, not the truth.

    Recomputed by a task and on demand. Every field can be derived from
    ``Booking`` rows, and if this row is ever stale the recompute fixes it —
    which is the property a running total does not have.
    """

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="risk_profiles"
    )
    provider = models.ForeignKey(
        "providers.ProviderProfile", on_delete=models.CASCADE, related_name="customer_risk"
    )

    total_bookings = models.PositiveIntegerField(default=0)
    completed = models.PositiveIntegerField(default=0)
    no_shows = models.PositiveIntegerField(default=0)
    cancelled = models.PositiveIntegerField(default=0)

    computed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "risk_customerrisk"
        ordering = ["-computed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "provider"], name="risk_one_profile_per_pair"
            )
        ]

    def __str__(self) -> str:
        return f"{self.customer} at {self.provider}"
