"""Pytest bootstrap.

Loads ``.env`` before Django starts so that a developer running ``pytest`` gets
the same database configuration as ``manage.py runserver``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent

# pytest-django imports the settings module during initial conftest loading,
# which is before this file is imported and well before pytest_configure runs.
# config.settings.base loads `.env` at import time so the database credentials
# are already in the environment by then.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")


def pytest_configure(config: pytest.Config) -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")


@pytest.fixture(autouse=True)
def _no_network_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a test tries to open a real socket.

    Without this, a stray ``requests.get`` in a test either hangs until the
    request times out or, worse, silently succeeds against a live service.
    """
    import socket

    real_socket = socket.socket

    class GuardedSocket(real_socket):  # type: ignore[misc, valid-type]
        def connect(self, address):
            host = address[0] if isinstance(address, tuple) else address
            if host not in {"127.0.0.1", "::1", "localhost", "testserver"}:
                raise RuntimeError(
                    f"Test attempted a real network connection to {host!r}. "
                    f"Use responses or django.test.RequestFactory instead."
                )
            return super().connect(address)

    monkeypatch.setattr(socket, "socket", GuardedSocket)
