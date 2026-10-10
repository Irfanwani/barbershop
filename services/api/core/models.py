"""Abstract models shared across the project."""

from __future__ import annotations

from datetime import UTC, datetime

from django.db import models
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    """Adds ``created_at`` / ``updated_at`` to a model.

    Every table in this project gets both. The old schema had neither, so there
    was no way to answer "when did this booking arrive?" without falling back on
    auto-increment ids.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def utcnow() -> datetime:
    """Timezone-aware now, in one place.

    Prefer Django's ``timezone.now()`` in application code; this exists for
    places that need it before settings are configured.
    """
    return datetime.now(tz=UTC)


class PublicIdModel(models.Model):
    """A short, non-sequential, guessable-resistant identifier.

    Booking references like ``BK-7QK4M2`` are shown to customers, so they must
    not be sequential — ``id=1`` would let anyone enumerate every booking.
    """

    class Meta:
        abstract = True


STATUS_CHOICES_HELP = _("Lifecycle of this record")
