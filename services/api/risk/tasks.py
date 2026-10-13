"""Scheduled risk work.

Two jobs, both cheap:

* **Refresh the cached profiles.** Nightly, because the score is also computed
  on demand at quote time and this only keeps the stored copy roughly current.
* **Sweep for flags.** Nightly, and it only ever raises flags - a human decides
  what a flag means.
"""

from __future__ import annotations

import logging

from celery import shared_task

from risk import scoring

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def refresh_risk_profiles() -> None:
    scoring.refresh_all()


@shared_task(ignore_result=True)
def sweep_risk_flags() -> None:
    """Look for the patterns worth a person's attention.

    Flags only. Nothing here changes what anybody pays or whether they can
    book - that is the whole point of calling them flags.
    """
    scoring.sweep_for_flags()
