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

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.gis.db import models
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


class ReminderPreferencesMixin(models.Model):
    """Which notifications this account has agreed to receive.

    Lives on the account rather than the device: a user who switches reminders
    off on one phone should stop getting them on every phone, and a user who
    reinstalls should not get everything back by default.
    """

    reminders_enabled = models.BooleanField(
        default=True,
        help_text="Appointment reminders. Turning this off stops booking reminders only.",
    )
    marketing_enabled = models.BooleanField(
        default=False,
        help_text="Offers and news. Opt-in: nobody wants an app that opts them in.",
    )

    class Meta:
        abstract = True


class CustomerProfile(ReminderPreferencesMixin, TimeStampedModel):
    """A customer's own details.

    Optional — a customer can browse without one. But "providers near me" needs
    somewhere to search from, and the old API stored the customer's coordinates
    in ``UserDetails``, which was created lazily and, when missing, caused a 500
    in the barber-list endpoint rather than a helpful prompt.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_profile",
        limit_choices_to={"role": "customer"},
    )

    photo = models.ImageField(upload_to="customers/", blank=True, null=True)
    about = models.TextField(blank=True, default="", max_length=500)
    address = models.CharField(max_length=300, blank=True, default="")

    # Nullable on purpose: a customer who has not granted location permission is
    # not an error, they just do not get distance-sorted results.
    coords = models.PointField(srid=4326, geography=True, null=True, blank=True)

    preferred_service_type = models.CharField(max_length=32, blank=True, default="")

    class Meta:
        db_table = "accounts_customer_profile"
        indexes = [
            models.Index(
                fields=["coords"], name="accounts_customer_coords_gist", opclasses=["gist"]
            ),
        ]

    def __str__(self) -> str:
        return f"Customer profile for {self.user}"

    @property
    def has_location(self) -> bool:
        return self.coords is not None


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


class SavedShop(TimeStampedModel):
    """A shop this customer wants to find again.

    The cheapest retention feature available, and the backbone of everything
    that tries to get a lapsed customer back: rebooking, nudges, "book again"
    from here.

    A note, because "my usual place" is not something the customer can infer
    later — it is the thing they would otherwise write in their head and
    forget.

    Unique per customer and shop, so saving twice is a no-op rather than a
    duplicate row that shows up twice in the list.
    """

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_shops"
    )
    provider = models.ForeignKey(
        "providers.ProviderProfile", on_delete=models.CASCADE, related_name="saved_by"
    )
    note = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        db_table = "accounts_saved_shop"
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "provider"], name="accounts_savedshop_unique_per_pair"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer} saved {self.provider}"


class NotificationKey(models.TextChoices):
    """The things this account can be told about.

    The same keys the app's settings screen shows. A booking confirmation is
    not the same category as "a new shop opened near you", and treating them
    the same is how notifications get muted wholesale — which then costs us
    the booking confirmations too.
    """

    BOOKING_CONFIRMATIONS = "bookingConfirmations", "Booking confirmations"
    BOOKING_REMINDERS = "bookingReminders", "Reminders"
    BOOKING_CHANGES = "bookingChanges", "Requests and messages"
    OFFERS_AND_PROMOTIONS = "offersAndPromotions", "Offers and promotions"
    NEW_SHOPS_NEARBY = "newShopsNearby", "New shops nearby"
    PRODUCT_NEWS = "productNews", "Product news"


#: Off unless the account says otherwise. Nothing may be opted in on the
#: user's behalf, which is the only way a preferences screen is trustworthy.
DEFAULT_PREFERENCES: dict[str, bool] = {
    NotificationKey.BOOKING_CONFIRMATIONS: True,
    NotificationKey.BOOKING_REMINDERS: True,
    NotificationKey.BOOKING_CHANGES: True,
    NotificationKey.OFFERS_AND_PROMOTIONS: False,
    NotificationKey.NEW_SHOPS_NEARBY: False,
    NotificationKey.PRODUCT_NEWS: False,
}

#: The two keys a provider cannot switch off, whatever the account says.
#:
#: A cancellation notice is not marketing. Letting someone opt out of being
#: told their own appointment was cancelled would be a bug with a settings
#: screen in front of it.
REQUIRED_KEYS = {NotificationKey.BOOKING_CONFIRMATIONS, NotificationKey.BOOKING_CHANGES}


class NotificationPreference(TimeStampedModel):
    """One account's answer for one category.

    Per key rather than one blob, so the reminder task can ask "who wants
    reminders?" in a query instead of loading every account and reading JSON.

    A row means "this account has an opinion". No row means the default
    applies, which is what every existing account should keep.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences"
    )
    key = models.CharField(max_length=32, choices=NotificationKey.choices)
    enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "accounts_notification_preference"
        constraints = [
            models.UniqueConstraint(fields=["user", "key"], name="accounts_notifpref_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.user} · {self.key}={'on' if self.enabled else 'off'}"


def notification_preferences(user) -> dict[str, bool]:
    """This account's effective answer for every category.

    One query. The task that sends reminders runs over every booking due, so
    it cannot afford to load a preference row per booking per person.
    """
    stored = dict(NotificationPreference.objects.filter(user=user).values_list("key", "enabled"))
    return {
        str(key): bool(stored.get(str(key), default))
        for key, default in DEFAULT_PREFERENCES.items()
    }


def wants_notification(user, key) -> bool:
    """Whether this account has agreed to be told about one thing.

    Required categories are always on. An account with no stored opinion gets
    the default.
    """
    if key in REQUIRED_KEYS:
        return True
    stored = NotificationPreference.objects.filter(user=user, key=key).first()
    if stored is None:
        return DEFAULT_PREFERENCES.get(key, False)
    return stored.enabled


def set_notification_preferences(user, wanted: dict[str, bool]) -> dict[str, bool]:
    """Record an account's answers, ignoring any attempt to mute a required one."""
    for key, value in wanted.items():
        if key not in DEFAULT_PREFERENCES:
            continue
        # Silently forced on rather than refused: the screen shows it as locked,
        # so a client sending false for it is out of date, not malicious.
        enabled = True if key in REQUIRED_KEYS else bool(value)
        NotificationPreference.objects.update_or_create(
            user=user, key=key, defaults={"enabled": enabled}
        )

    return notification_preferences(user)
