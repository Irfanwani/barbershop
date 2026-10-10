"""Production settings.

Every value here is required. This module raises :class:`MissingSettingError` at
import time rather than letting the process boot with a ``None`` somewhere and
fail at 3am when a customer tries to log in.
"""

from config import env
from config.env import MissingSettingError
from config.settings.base import *
from config.settings.base import BASE_DIR

DEBUG = False

SECRET_KEY = env.get("SECRET_KEY")
ALLOWED_HOSTS = env.get_list("ALLOWED_HOSTS", [])

# Absent configuration that only bites under load is worth failing loudly for.
REQUIRED = [
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "EMAIL_HOST",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "DEFAULT_FROM_EMAIL",
    "RAZORPAY_KEY_ID",
    "RAZORPAY_KEY_SECRET",
    "RAZORPAY_WEBHOOK_SECRET",
    "FIELD_ENCRYPTION_KEY",
]
_missing = [key for key in REQUIRED if not env.raw(key)]
if _missing:
    raise MissingSettingError(
        "Missing required production environment variables: "
        + ", ".join(_missing)
        + ". See services/api/.env.example."
    )

# --- security headers -------------------------------------------------------

SECURE_SSL_REDIRECT = env.get_bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.get_int("SECURE_HSTS_SECONDS", 60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"

# --- email ------------------------------------------------------------------

EMAIL_BACKEND = env.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_TIMEOUT = env.get_int("EMAIL_TIMEOUT", 10)

# --- media ------------------------------------------------------------------

if env.get_bool("USE_S3", default=False):
    AWS_ACCESS_KEY_ID = env.get("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = env.get("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = env.get("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = env.get("AWS_S3_REGION_NAME", "ap-south-1")
    AWS_QUERYSTRING_AUTH = False
    AWS_DEFAULT_ACL = None
    AWS_S3_FILE_OVERWRITE = False
    AWS_S3_OBJECT_PARAMETERS = {"CacheControl": "max-age=31536000, immutable"}

    STORAGES = {
        "default": {"BACKEND": "core.storage.PublicMediaStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    MEDIA_ROOT = BASE_DIR / "media"

# --- proxy ------------------------------------------------------------------

# Behind Render/Railway/nginx there is exactly one hop; more is a spoofing vector.
NUM_PROXIES = env.get_int("NUM_PROXIES", 1)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- database ---------------------------------------------------------------

CONN_MAX_AGE = env.get_int("POSTGRES_CONN_MAX_AGE", 60)
DATABASES["default"]["CONN_MAX_AGE"] = CONN_MAX_AGE

LOGGING = {
    **LOGGING,
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "barbershop": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}
