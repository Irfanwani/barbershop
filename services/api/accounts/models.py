"""Users, roles, and the credentials that belong to an account.

Note on migrations: the legacy ``UserDetails`` / ``BarberDetails`` /
``BankDetails`` / ``ServicesDetails`` / ``Emails`` / ``SignUpCodes`` /
``PasswordCodes`` models still exist in ``accounts/migrations`` because their
tables hold production data. They are read by a data migration into the new
models and then deleted — see ``0005_migrate_legacy_profiles`` and
``0006_remove_legacy_profiles``.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel


class Role(models.TextChoices):
    """Which side of the marketplace the account sits on.

    The old API inferred this by checking whether a ``BarberDetails`` row existed
    and returning ``is_barber``, which meant a half-onboarded account reported
    contradictory values from different endpoints. Storing it explicitly means
    ``role`` and "does a profile exist" cannot disagree.
    """

    CUSTOMER = "customer", "Customer"
    PROVIDER = "provider", "Service provider"


class User(AbstractUser):
    """The account. One row per person, regardless of role."""

    email = models.EmailField(unique=True)

    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.CUSTOMER,
        help_text="Which side of the marketplace this account operates on.",
    )

    phone = models.CharField(max_length=20, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)

    # Supersedes the old `Emails` table, whose only job was to record that an
    # address had been confirmed.
    is_verified = models.BooleanField(
        default=False,
        help_text="True once the address on this account has been confirmed.",
    )

    verified_at = models.DateTimeField(null=True, blank=True)

    timezone_name = models.CharField(
        max_length=64,
        blank=True,
        help_text="IANA zone used to render appointment times, e.g. Asia/Kolkata.",
    )

    class Meta:
        db_table = "accounts_user"
        ordering = ["-date_joined"]
        indexes = [models.Index(fields=["role", "is_verified"])]

    def __str__(self) -> str:
        return self.username

    @property
    def is_provider(self) -> bool:
        return self.role == Role.PROVIDER

    @property
    def is_customer(self) -> bool:
        return self.role == Role.CUSTOMER

    @property
    def display_name(self) -> str:
        return self.get_full_name() or self.username

    @property
    def onboarding_complete(self) -> bool:
        """Whether the account has enough data to be useful.

        A provider needs a shop profile and at least one service before they can
        be booked. A customer is usable as soon as they are verified.
        """
        if not self.is_verified:
            return False
        if self.is_customer:
            return True
        profile = getattr(self, "provider_profile", None)
        return bool(profile and profile.services.filter(is_active=True).exists())

    def mark_verified(self) -> None:
        self.is_verified = True
        self.verified_at = timezone.now()


class VerificationCode(TimeStampedModel):
    """A single-use, expiring code for confirming an email or resetting a password.

    Stored hashed. The plaintext exists only in the email that was sent.
    """

    class Purpose(models.TextChoices):
        SIGNUP = "signup", "Email verification"
        RESET = "reset", "Password reset"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="verification_codes")
    purpose = models.CharField(max_length=8, choices=Purpose.choices)
    code_hash = models.CharField(max_length=64, db_index=True)

    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "accounts_verification_code"
        indexes = [models.Index(fields=["user", "purpose", "consumed_at"])]

    def __str__(self) -> str:
        return f"{self.purpose} code for {self.user}"

    @property
    def is_usable(self) -> bool:
        return self.consumed_at is None and self.expires_at > timezone.now()

    def consume(self) -> None:
        self.consumed_at = timezone.now()
        self.save(update_fields=["consumed_at", "updated_at"])


class PushToken(TimeStampedModel):
    """A device's push-notification token.

    The old ``haircut.NotificationTokens`` shipped every provider's tokens back
    to the booking client, which then called an external push service itself.
    That leaked device tokens to any user who could create a booking, and put the
    fan-out on the wrong side of the wire.
    """

    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="push_tokens")

    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(
        max_length=16,
        choices=Platform.choices,
        blank=True,
        help_text="Best effort; unknown values are kept rather than rejected.",
    )
    active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_push_token"
        ordering = ["-last_seen_at"]

    def __str__(self) -> str:
        return f"{self.user} · {self.platform or 'unknown'}"


class LoginAudit(TimeStampedModel):
    """A record of each sign-in.

    There was no way to answer "was this account compromised?" before. This is
    deliberately cheap: an indexed timestamp, an IP, and the outcome.
    """

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="login_audits"
    )
    email_attempted = models.EmailField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    succeeded = models.BooleanField()
    reason = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = "accounts_login_audit"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self) -> str:
        outcome = "ok" if self.succeeded else "failed"
        return f"{self.email_attempted} {outcome}"


# ---------------------------------------------------------------------------
# Legacy models
#
# Imported rather than defined here so the superseded schema does not crowd out
# the current one. They stay importable until the data migration and the
# DeleteModel migration that follows it retire them.
#
# Importing them into this module keeps the app registry — and therefore the
# autodetector — seeing them under their original `accounts.models.*` path.
# ---------------------------------------------------------------------------

from accounts.legacy import (  # noqa: E402
    ACCOUNT_CHOICES,
    BUSINESS_CHOICES,
    SERVICE_CHOICES,
    BankDetails,
    BarberDetails,
    Emails,
    PasswordCodes,
    ServicesDetails,
    SignUpCodes,
    UserDetails,
    unique_validator,
)

# Grouped rather than sorted: which names are current and which are on their
# way out is the single most useful thing this list can say.
__all__ = [  # noqa: RUF022
    # current
    "LoginAudit",
    "PushToken",
    "Role",
    "User",
    "VerificationCode",
    # legacy, see the import block above
    "ACCOUNT_CHOICES",
    "BUSINESS_CHOICES",
    "SERVICE_CHOICES",
    "BankDetails",
    "BarberDetails",
    "Emails",
    "PasswordCodes",
    "ServicesDetails",
    "SignUpCodes",
    "UserDetails",
    "unique_validator",
]
