"""Local development settings. Never used in production."""

from config import env
from config.settings.base import *

DEBUG = True

SECRET_KEY = env.get("SECRET_KEY", "django-insecure-local-development-key-not-for-production")

ALLOWED_HOSTS = env.get_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"])

# Android emulators reach the host machine at 10.0.2.2.
if env.get_bool("ANDROID_EMULATOR", default=True):
    ALLOWED_HOSTS += ["10.0.2.2"]

# Emails print to the console instead of being sent.
EMAIL_BACKEND = env.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")

# A throwaway key so developers can store bank details without ceremony. Rotating it
# makes previously-saved rows unreadable, which is fine locally and never in prod.
FIELD_ENCRYPTION_KEY = env.get("FIELD_ENCRYPTION_KEY", "local-development-encryption-key")

# Media lives on disk so you can see exactly what was uploaded.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Never check a manifest during development — it hides missing-file bugs until deploy.
WHITENOISE_AUTOREFRESH = True

EMAIL_BACKEND = env.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
