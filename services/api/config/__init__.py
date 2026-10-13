"""Import the Celery app here so it is always the current app.

Without this, ``@shared_task`` binds to Celery's default app when nothing has
imported ``config.celery`` - which is not configured from Django settings, so
``task_always_eager`` and every other setting is silently ignored and
``@app.task`` registrations land on an app no worker is running. It cost a 500
the first time an endpoint called ``.delay()`` in a test, and would have cost a
worker that never picks anything up in production.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
