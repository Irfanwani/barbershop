"""Service providers: shop profiles, their service menu, and payout accounts."""

from __future__ import annotations

from datetime import time
from decimal import Decimal

from django.conf import settings
from django.contrib.gis.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import F, Q
from django.utils import timezone

from accounts.models import ReminderPreferencesMixin
from core.fields import EncryptedTextField
from core.models import TimeStampedModel
from core.money import format_minor


class ServiceType(models.TextChoices):
    """What kind of establishment this is.

    The first five values match the legacy ``SERVICE_CHOICES`` exactly so the
    data migration is a straight copy rather than a lossy remap.
    """

    BARBERSHOP = "barbershop", "Barber shop"
    HAIR_SALON = "hair_salon", "Hair salon"
    BEAUTY_SALON = "beauty_salon", "Beauty salon"
    FULL_SERVICE_SALON = "full_service_salon", "Full service salon"
    SPA = "spa", "Spa"
    MASSAGE = "massage", "Massage"
    OTHER = "other", "Other"


class ProviderProfile(ReminderPreferencesMixin, TimeStampedModel):
    """The public-facing shop record behind a provider account.

    One per provider user. ``coords`` is ``geography`` rather than geometry so
    that ``ST_Distance`` is calculated on a spheroid — a customer in Delhi
    should not be told a barber is 400m away because the earth was treated as
    flat.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_profile",
        limit_choices_to={"role": "provider"},
    )

    display_name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")

    service_type = models.CharField(
        max_length=32, choices=ServiceType.choices, default=ServiceType.BARBERSHOP, db_index=True
    )

    photo = models.ImageField(upload_to="providers/", blank=True, null=True)
    cover_photo = models.ImageField(upload_to="providers/covers/", blank=True, null=True)

    # Free-text address for display; `coords` is what search actually uses.
    address = models.CharField(max_length=300, blank=True, default="")
    coords = models.PointField(srid=4326, geography=True)

    contact_phone = models.CharField(max_length=20, blank=True, default="")

    employee_count = models.PositiveSmallIntegerField(default=1)

    opening_time = models.TimeField(default="09:00")
    closing_time = models.TimeField(default="20:00")
    slot_interval_minutes = models.PositiveSmallIntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(240)],
        help_text="Granularity of the bookable slots.",
    )

    is_accepting_bookings = models.BooleanField(default=True)
    requires_approval = models.BooleanField(
        default=False,
        help_text="When true, a booking starts as pending and the provider accepts it.",
    )

    # Denormalised from Review. Reading the aggregate on every search result is
    # a correlated subquery per provider; this is one indexed column.
    rating_average = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal("0.00"))
    rating_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "providers_profile"
        ordering = ["display_name"]
        indexes = [
            models.Index(fields=["service_type", "is_accepting_bookings"]),
            models.Index(fields=["rating_average"]),
            # GiST index on the geography column. Without it, "providers near
            # me" degrades to a sequential scan over every shop on the platform.
            models.Index(
                fields=["coords"],
                name="providers_profile_coords_gist",
                opclasses=["gist"],
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(employee_count__gte=1),
                name="providers_profile_employee_count_gte_1",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name

    @property
    def latitude(self) -> float | None:
        return self.coords.y if self.coords else None

    @property
    def longitude(self) -> float | None:
        return self.coords.x if self.coords else None

    @property
    def active_service_count(self) -> int:
        return self.services.filter(is_active=True).count()

    @property
    def is_bookable(self) -> bool:
        """Whether this provider can take a booking right now."""
        return self.is_accepting_bookings and self.active_service_count > 0

    @property
    def starting_price(self) -> int | None:
        return (
            self.services.filter(is_active=True)
            .order_by("price")
            .values_list("price", flat=True)
            .first()
        )

    @property
    def starting_price_display(self) -> str | None:
        price = self.starting_price
        return format_minor(price) if price is not None else None

    def is_open_at(self, moment=None) -> bool:
        moment = moment or timezone.localtime()
        return self.opening_time <= moment.time() <= self.closing_time

    def refresh_rating(self, save: bool = True) -> Decimal:
        """Recompute the cached rating from its reviews."""
        stats = self.reviews.aggregate(
            # Django infers Avg's output as a float. Left that way, 4.5 averages
            # to 4.499999999999999 and the cached value drifts a little every time
            # it is recomputed.
            average=models.Avg(
                "rating",
                output_field=models.DecimalField(max_digits=3, decimal_places=2),
            ),
            count=models.Count("id"),
        )
        self.rating_average = (stats["average"] or Decimal("0.00")).quantize(Decimal("0.01"))
        self.rating_count = stats["count"] or 0
        if save:
            self.save(update_fields=["rating_average", "rating_count", "updated_at"])
        return self.rating_average

    def owns_service(self, service_id: int) -> bool:
        return self.services.filter(pk=service_id).exists()

    def hours_for(self, weekday: int) -> WorkingHours | None:
        """The hours row for a weekday, or None if the shop never set one.

        None means "fall back to the shop's own opening and closing time", which
        is what every shop had before per-day hours existed. Treating a missing
        row as "closed" would silently shut every provider on the platform.
        """
        return self.hours.filter(weekday=weekday).first()

    def is_open_on(self, weekday: int) -> bool:
        hours = self.hours_for(weekday)
        if hours is None:
            # Monday to Saturday by default. A barber's shop that is shut on
            # Sunday is the exception, not the rule.
            return weekday != 6
        return not hours.is_closed

    def day_bounds(self, weekday: int) -> tuple[time, time] | None:
        """The opening and closing time for a weekday, or None if closed."""
        hours = self.hours_for(weekday)
        if hours is None:
            return self.opening_time, self.closing_time
        if hours.is_closed:
            return None
        return hours.opens_at, hours.closes_at


class WorkingHours(models.Model):
    """Per-weekday opening hours.

    A single ``opening_time``/``closing_time`` pair on the shop cannot express
    "closed on Sunday, and only until 6pm on Saturday", which is how most shops
    actually run. This is the on/off control the provider sets.
    """

    provider = models.ForeignKey(ProviderProfile, on_delete=models.CASCADE, related_name="hours")
    WEEKDAYS = (
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    )

    weekday = models.PositiveSmallIntegerField(
        choices=WEEKDAYS,
        validators=[MinValueValidator(0), MaxValueValidator(6)],
        help_text="0 = Monday. Django's date.weekday() convention.",
    )
    is_closed = models.BooleanField(default=False)
    opens_at = models.TimeField(default="09:00")
    closes_at = models.TimeField(default="20:00")

    class Meta:
        db_table = "providers_workinghours"
        ordering = ["weekday"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "weekday"], name="providers_hours_provider_weekday_uniq"
            ),
            # A shift that ends before it starts is a typo, not an all-nighter.
            models.CheckConstraint(
                condition=Q(is_closed=True) | Q(opens_at__lt=F("closes_at")),
                name="providers_hours_closes_after_opens",
            ),
        ]

    def __str__(self) -> str:
        day = self.get_weekday_display()
        if self.is_closed:
            return f"{day}: closed"
        return f"{day}: {self.opens_at:%H:%M}-{self.closes_at:%H:%M}"

    def as_dict(self) -> dict[str, object]:
        return {
            "weekday": self.weekday,
            "weekday_label": self.get_weekday_display(),
            "is_closed": self.is_closed,
            "opens_at": self.opens_at.strftime("%H:%M"),
            "closes_at": self.closes_at.strftime("%H:%M"),
        }


class Service(TimeStampedModel):
    """One thing a provider sells.

    ``price`` is the provider's own price, in paise, before the platform fee. The
    old schema stored the post-commission figure and applied a further 10% inside
    the view, so the number in the database was neither the shelf price nor the
    charged price.
    """

    provider = models.ForeignKey(ProviderProfile, on_delete=models.CASCADE, related_name="services")

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")

    price = models.PositiveIntegerField(
        help_text="Provider's price in the smallest currency unit (paise).",
    )
    duration_minutes = models.PositiveSmallIntegerField(
        default=30, validators=[MinValueValidator(5), MaxValueValidator(600)]
    )

    is_active = models.BooleanField(
        default=True, help_text="Retired services stay on old bookings but cannot be booked."
    )

    class Meta:
        db_table = "providers_service"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "name"], name="providers_service_provider_name_uniq"
            )
        ]
        indexes = [
            models.Index(fields=["provider", "is_active"]),
            models.Index(fields=["is_active", "price"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.provider.display_name})"

    @property
    def price_display(self) -> str:
        return format_minor(self.price)


class BusinessType(models.TextChoices):
    INDIVIDUAL = "individual", "Individual"
    PARTNERSHIP = "partnership", "Partnership"
    PROPRIETORSHIP = "proprietorship", "Proprietorship"
    COMPANY = "company", "Company"
    NOT_YET_REGISTERED = "not_yet_registered", "Not yet registered"


class AccountType(models.TextChoices):
    SAVINGS = "savings", "Savings"
    CURRENT = "current", "Current"


class ProviderPayout(TimeStampedModel):
    """Where the provider's earnings are sent.

    The account number is encrypted at rest (:mod:`core.fields`) and every
    serializer masks it. The old ``accounts.BankDetails`` stored it as a
    ``PositiveBigIntegerField`` in plaintext and returned it verbatim through a
    ``fields = '__all__'`` serializer to anyone who asked.
    """

    class VerificationStatus(models.TextChoices):
        PENDING = "pending", "Pending verification"
        SUBMITTED = "submitted", "Submitted to Razorpay"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"

    provider = models.OneToOneField(
        ProviderProfile, on_delete=models.CASCADE, related_name="payout"
    )

    business_name = models.CharField(max_length=120)
    business_type = models.CharField(
        max_length=32, choices=BusinessType.choices, default=BusinessType.INDIVIDUAL
    )
    beneficiary_name = models.CharField(max_length=120)

    account_number = EncryptedTextField(help_text="Encrypted at rest. Never returned in full.")
    ifsc_code = EncryptedTextField(max_length=11, help_text="Encrypted at rest.")
    account_type = models.CharField(
        max_length=16, choices=AccountType.choices, default=AccountType.SAVINGS
    )

    # Assigned by Razorpay when the fund account is created.
    razorpay_account_id = models.CharField(max_length=64, blank=True, default="")
    razorpay_destination = models.CharField(max_length=128, blank=True, default="")

    verification_status = models.CharField(
        max_length=16,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        db_index=True,
    )
    rejection_reason = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        db_table = "providers_payout"
        verbose_name_plural = "provider payouts"

    def __str__(self) -> str:
        return f"Payout for {self.provider.display_name} ({self.verification_status})"

    @property
    def account_number_masked(self) -> str:
        from core.fields import mask

        return mask(self.account_number or "")

    @property
    def ifsc_code_masked(self) -> str:
        from core.fields import mask

        return mask(self.ifsc_code or "", keep=0)

    @property
    def is_verified(self) -> bool:
        return self.verification_status == self.VerificationStatus.VERIFIED
