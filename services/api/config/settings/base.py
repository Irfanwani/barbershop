"""Settings shared by every environment.

Anything that differs between local, test and production belongs in a sibling
module that imports from here — never a ``if DEBUG:`` branch.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from config import env

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load `.env` here rather than in manage.py or a test conftest: settings are
# imported by every entrypoint — manage.py, gunicorn, pytest, celery — and each
# one loads at a different moment. Doing it in one place means a developer never
# has to remember to export the database password before running the tests.
#
# `override=False` so a real environment variable always wins over the file.
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env", override=False)
except ImportError:  # pragma: no cover - dotenv is a hard dependency
    pass

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

SECRET_KEY = env.get("SECRET_KEY", "django-insecure-development-only-do-not-use-in-production")
DEBUG = False
ALLOWED_HOSTS = env.get_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1", "[::1]"])

CSRF_TRUSTED_ORIGINS = env.get_list("CSRF_TRUSTED_ORIGINS", [])
CORS_ALLOWED_ORIGINS = env.get_list("CORS_ALLOWED_ORIGINS", [])
CORS_ALLOW_ALL_ORIGINS = env.get_bool("CORS_ALLOW_ALL_ORIGINS", default=DEBUG)

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "knox",
    "drf_spectacular",
    "corsheaders",
    "django_cleanup.apps.CleanupConfig",
]

LOCAL_APPS = [
    "core",
    "accounts",
    "providers",
    "bookings",
    "reviews",
    "payments",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.gzip.GZipMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = env.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files and media
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").is_dir() else []

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Uploaded images are capped at 5 MB and must be a real image, not a renamed file.
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Declared here, used only when USE_S3 is on (see config.settings.prod). They
# exist unconditionally so that `core.storage.PublicMediaStorage` is typed even
# in the development settings module that never turns S3 on.
USE_S3 = env.get_bool("USE_S3", default=False)
AWS_ACCESS_KEY_ID = env.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = env.get("AWS_SECRET_ACCESS_KEY", "")
AWS_STORAGE_BUCKET_NAME = env.get("AWS_STORAGE_BUCKET_NAME", "")
AWS_S3_REGION_NAME = env.get("AWS_S3_REGION_NAME", "ap-south-1")

# ---------------------------------------------------------------------------
# Database — PostGIS. `django.contrib.gis` is not optional for this project;
# provider search is a radius query, not a Python loop over coordinates.
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": env.get("POSTGRES_DB", "barbershop"),
        "USER": env.get("POSTGRES_USER", "postgres"),
        "PASSWORD": env.get("POSTGRES_PASSWORD", ""),
        "HOST": env.get("POSTGRES_HOST", "localhost"),
        "PORT": env.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": env.get_int("POSTGRES_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "connect_timeout": env.get_int("POSTGRES_CONNECT_TIMEOUT", 10),
        },
        "TEST": {
            "NAME": env.get("TEST_POSTGRES_DB", "test_barbershop"),
        },
    }
}

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "knox.auth.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Opt in, never opt out. The old API defaulted to AllowAny and relied on every
    # view remembering to set IsAuthenticated; one that forgot shipped a hole.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "core.pagination.DefaultPagination",
    "PAGE_SIZE": env.get_int("DEFAULT_PAGE_SIZE", 20),
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "auth": env.get("THROTTLE_RATE_AUTH", "20/min"),
        "password_reset": env.get("THROTTLE_RATE_PASSWORD_RESET", "5/min"),
        "booking": env.get("THROTTLE_RATE_BOOKING", "30/min"),
    },
    "EXCEPTION_HANDLER": "core.exceptions.api_exception_handler",
    "DATETIME_FORMAT": "iso-8601",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "BarberShop API",
    "DESCRIPTION": (
        "REST API for the BarberShop marketplace. Connects customers with barbers, "
        "salons and spas. Geospatial provider search, bookings, Razorpay payments and reviews."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
    "TAGS": [
        {"name": "auth", "description": "Registration, login, tokens, password reset."},
        {"name": "me", "description": "The authenticated user's own account and profile."},
        {
            "name": "providers",
            "description": "Service providers: discovery, services, availability.",
        },
        {"name": "bookings", "description": "Appointments between a customer and a provider."},
        {"name": "reviews", "description": "Ratings and comments left after a booking."},
        {"name": "payments", "description": "Razorpay order creation and webhook confirmation."},
    ],
    # A custom renderer so the committed schema is byte-stable: without it,
    # drf-spectacular orders the operations inside a path by set iteration, which
    # changes with Python's hash seed and makes the CI drift check a coin flip.
    # See config/renderers.py.
    "DEFAULT_RENDERER_CLASSES": ["config.renderers.CanonicalOpenApiYamlRenderer"],
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
}

# ---------------------------------------------------------------------------
# Authentication tokens (django-rest-knox)
# ---------------------------------------------------------------------------

REST_KNOX = {
    "TOKEN_TTL": timedelta(hours=env.get_int("AUTH_TOKEN_TTL_HOURS", 24 * 7)),
    # Sliding expiry: an active user's session does not die mid-appointment.
    "AUTO_REFRESH": True,
    "TOKEN_LIMIT_PER_USER": env.get_int("AUTH_TOKEN_LIMIT_PER_USER", 10),
    "AUTO_REFRESH_MAX_LIMIT": env.get_int("AUTH_TOKEN_AUTO_REFRESH_MAX_LIMIT", 100),
    "MIN_REFRESH_INTERVAL": env.get_int("AUTH_TOKEN_MIN_REFRESH_SECONDS", 60),
}

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

EMAIL_BACKEND = env.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env.get("EMAIL_HOST", "")
EMAIL_PORT = env.get_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env.get_bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env.get_bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = env.get_int("EMAIL_TIMEOUT", 10)
DEFAULT_FROM_EMAIL = env.get("DEFAULT_FROM_EMAIL", "BarberShop <no-reply@barbershop.local>")

# ---------------------------------------------------------------------------
# Payments — Razorpay
# ---------------------------------------------------------------------------

RAZORPAY_KEY_ID = env.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = env.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = env.get("RAZORPAY_WEBHOOK_SECRET", "")

# Charged on top of the provider's price and shown as a separate line on the
# booking. Bookings snapshot their fee at creation, so changing this affects new
# bookings only — a fee that changes under an existing booking is a fee the
# customer did not agree to.
PLATFORM_FEE_PERCENT = env.get_int("PLATFORM_FEE_PERCENT", 1)

# ---------------------------------------------------------------------------
# Push notifications
# ---------------------------------------------------------------------------

PUSH_NOTIFICATION_URL = env.get("PUSH_NOTIFICATION_URL", "")

# ---------------------------------------------------------------------------
# Celery — scheduled work
# ---------------------------------------------------------------------------
#
# Reminders and expiry run on a worker, not in a request. Redis is both broker
# and result backend; a deployment that only runs the API and not a worker will
# serve requests fine and silently send no reminders, so the healthcheck below
# is what makes that visible.

CELERY_BROKER_URL = env.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env.get("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = env.get_bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = env.get("CELERY_TIMEZONE", "UTC")
CELERY_ENABLE_UTC = True
# A reminder that fails twice will not succeed on a third try minutes later;
# anything worth retrying is retried by the caller instead.
CELERY_TASK_ACKS_LATE = True

# ---------------------------------------------------------------------------
# Field-level encryption for provider bank details.
# Losing this key means losing access to stored account numbers. There is
# deliberately no default: production refuses to boot without it.
# ---------------------------------------------------------------------------

FIELD_ENCRYPTION_KEY = env.get("FIELD_ENCRYPTION_KEY", "")

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

LOG_LEVEL = env.get("LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# Legacy shims
#
# The pre-v1 code in accounts/, haircut/ and payments/ reads these names. They
# exist only until that code is replaced by the /api/v1/ API and are deleted in
# the same commit that retires it.
# ---------------------------------------------------------------------------

RAZOR_KEY_ID = RAZORPAY_KEY_ID
RAZOR_KEY_SECRET = RAZORPAY_KEY_SECRET
RAZOR_URL = "https://api.razorpay.com/v1/fund_accounts"
LOCAL_PASSWORD = env.get("POSTGRES_PASSWORD", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "INFO", "handlers": ["console"], "propagate": False},
    },
}
