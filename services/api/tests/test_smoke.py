"""Smoke tests: does the project boot and is its configuration coherent?

These are not filler. They fail loudly if a settings module, an installed app or
a middleware entry is wrong — which is exactly the class of breakage that is
tedious to diagnose from a real 500.
"""

import os

import django
from django.conf import settings
from django.urls import reverse


def test_django_is_configured():
    assert django.VERSION[:2] == (5, 2)
    assert settings.ROOT_URLCONF == "config.urls"


def test_debug_is_off_under_the_test_settings():
    assert settings.DEBUG is False


def test_auth_user_model_is_swapped():
    assert settings.AUTH_USER_MODEL == "accounts.User"


def test_every_installed_app_imports():
    from django.apps import apps

    apps.check_apps_ready()


def test_api_does_not_default_to_allow_any():
    """The old API defaulted to AllowAny and forgot to opt in on some views."""
    from rest_framework.settings import api_settings

    allowed = api_settings.DEFAULT_PERMISSION_CLASSES
    assert [cls.__name__ for cls in allowed] == ["IsAuthenticated"]


def test_healthcheck_is_reachable():
    from django.test import Client

    response = Client().get(reverse("healthcheck"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_postgis_backend_is_in_use():
    assert "gis" in settings.DATABASES["default"]["ENGINE"]


def test_production_settings_refuse_to_boot_without_secrets(monkeypatch):
    """A missing SECRET_KEY must fail at import, not at 3am."""
    from config import env

    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    monkeypatch.delitem(os.environ, "DJANGO_SETTINGS_MODULE")

    with pytest.raises(env.MissingSettingError):
        import config.settings.prod  # noqa: F401


import pytest  # noqa: E402  (imported late so the module-level django setup wins)
