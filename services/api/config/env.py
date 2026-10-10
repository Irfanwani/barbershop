"""Typed accessors for environment variables.

Settings modules read configuration through these helpers rather than calling
``os.environ`` directly. That gives us three things the raw dict does not:
coercion, defaults, and a loud failure when a *required* variable is missing in
production instead of a mysterious ``None`` three layers deep at runtime.
"""

from __future__ import annotations

import os
from typing import Any

_TRUE = {"1", "true", "t", "yes", "y", "on"}
_FALSE = {"0", "false", "f", "no", "n", "off"}


class MissingSettingError(RuntimeError):
    """Raised when a setting with no default is absent from the environment."""


def raw(key: str, default: str | None = None) -> str | None:
    value = os.environ.get(key)
    return default if value is None or value == "" else value


def get(key: str, default: str | None = None) -> str:
    """Return ``key`` as a string, raising if it is absent and has no default."""
    value = raw(key, default)
    if value is None:
        raise MissingSettingError(
            f"The environment variable {key!r} is required but was not set. "
            f"Copy services/api/.env.example to .env and fill it in."
        )
    return value


def get_bool(key: str, default: bool = False) -> bool:
    value = raw(key)
    if value is None:
        return default
    lowered = value.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ValueError(f"{key}={value!r} is not a valid boolean.")


def get_int(key: str, default: int) -> int:
    value = raw(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{key}={value!r} is not a valid integer.") from exc


def get_list(key: str, default: list[str] | None = None, sep: str = ",") -> list[str]:
    value = raw(key)
    if value is None:
        return list(default or [])
    return [item.strip() for item in value.split(sep) if item.strip()]


def get_any(key: str, default: Any = None) -> Any:
    """Return a literal (dict/list/number) parsed from JSON, or ``default``."""
    import json

    value = raw(key)
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{key}={value!r} is not valid JSON.") from exc
