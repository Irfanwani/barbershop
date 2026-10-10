"""Settings package.

``DJANGO_SETTINGS_MODULE`` should be one of :mod:`config.settings.dev`,
:mod:`config.settings.test` or :mod:`config.settings.prod`.
"""

from config.env import MissingSettingError

__all__ = ["MissingSettingError"]
