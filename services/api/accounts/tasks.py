"""Scheduled account housekeeping.

Small jobs, run nightly. None of them are urgent; all of them were previously
never run at all.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from accounts.models import PushToken, VerificationCode

logger = logging.getLogger(__name__)

#: A device that has not checked in for this long is gone. Keeping its token
#: means every reminder retries a push that can never arrive.
STALE_TOKEN_DAYS = 90


@shared_task(name="accounts.tasks.expire_stale_tokens")
def expire_stale_tokens() -> dict[str, int]:
    """Deactivate push tokens from devices that have stopped checking in."""
    cutoff = timezone.now() - timedelta(days=STALE_TOKEN_DAYS)
    stale = PushToken.objects.filter(active=True, last_seen_at__lt=cutoff)

    count = stale.update(active=False)
    if count:
        logger.info("Deactivated %d stale push token(s)", count)
    return {"deactivated": count}


@shared_task(name="accounts.tasks.prune_used_verification_codes")
def prune_used_verification_codes() -> dict[str, int]:
    """Delete verification codes that were used or have expired.

    They are hashed and single-use, so they are not a live risk, but they are a
    growth-only table otherwise.
    """
    cutoff = timezone.now() - timedelta(days=7)
    stale = VerificationCode.objects.filter(
        consumed_at__isnull=False, consumed_at__lt=cutoff
    ) | VerificationCode.objects.filter(expires_at__lt=cutoff)

    count, _ = stale.delete()
    if count:
        logger.info("Pruned %d spent verification code(s)", count)
    return {"deleted": count}
