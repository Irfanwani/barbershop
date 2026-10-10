"""Settings used by the automated test suite.

Two things matter here beyond speed: the tests must not send real email or push
notifications, and throttling must not make a test fail because it ran six
requests in a second.
"""

from config import env
from config.settings.base import *

DEBUG = False

SECRET_KEY = "test-secret-key-not-used-outside-the-test-runner"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

# Nothing leaves the machine during a test run.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PUSH_NOTIFICATION_URL = ""
RAZORPAY_KEY_ID = "rzp_test_key"
RAZORPAY_KEY_SECRET = "rzp_test_secret"
RAZORPAY_WEBHOOK_SECRET = "webhook_test_secret"

FIELD_ENCRYPTION_KEY = "test-encryption-key"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Salted-hash hashing: scrypt would be correct in production and ruinously slow here.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Hashing 10k passwords is not the point of any test in this repo.
AUTH_PASSWORD_VALIDATORS = []

# Test isolation matters more than the abuse protection does. Scoped throttles are
# disabled by sending every request through the AllowAny-by-default throttle scope.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {},
}

# PostGIS behaviour cannot be faked, so the suite still needs a real database.
DATABASES = {
    "default": {
        **DATABASES["default"],
        "NAME": env.get("POSTGRES_DB", "barbershop"),
        "TEST": {"NAME": env.get("TEST_POSTGRES_DB", "test_barbershop")},
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "CRITICAL"},
}

# --- speed ------------------------------------------------------------------

DEBUG_PROPAGATE_EXCEPTIONS = True
MESSAGE_STORAGE = "django.contrib.messages.storage.fallback.FallbackStorage"
