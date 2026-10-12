"""Service providers: shop profiles, their service menu, and payout accounts."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

from django.conf import settings
from django.contrib.gis.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import F, Q
from django.utils.text import slugify

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

    #: The shop's own address on the public web.
    #:
    #: This is the acquisition channel for an independent — a link pasted into
    #: an Instagram bio, a WhatsApp status, a signature. It has to be
    #: memorable enough to type and stable enough to print on a leaflet, so it
    #: is the shop's own and can be changed when a shop rebrands.
    #:
    #: Changing it breaks the old URL, deliberately: a redirect would keep
    #: every printed leaflet working, but would also mean the shop can never
    #: start again on a name it has outgrown, because the old one would
    #: shadow it forever.
    slug = models.SlugField(max_length=80, unique=True, blank=True)

    #: The zone this shop's opening hours are written in.
    #:
    #: Blank means "ask the account", and failing that the server's own. Hours
    #: are stored as naive local times — a barber says "I open at nine" and
    #: means nine where they work — so somewhere that value has to be anchored
    #: to a real place, and this is where.
    #:
    #: Every previous interpretation used the *server's* timezone, which is
    #: correct for a single-country marketplace and quietly wrong the moment
    #: the second one exists: a 09:00 opening in Bengaluru checked against UTC
    #: is 14:30, so the shop appears open four and a half hours late and closes
    #: at 02:30 local.
    timezone_name = models.CharField(
        max_length=64,
        blank=True,
        help_text="IANA zone for this shop's hours, e.g. Asia/Kolkata. Falls back to the account.",
    )
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

    #: How far ahead a customer may cancel for free. Copied onto each booking at
    #: the time it is made, so tightening this cannot retroactively change what
    #: somebody already agreed to.
    cancellation_window_hours = models.PositiveSmallIntegerField(
        default=24,
        validators=[MinValueValidator(0), MaxValueValidator(720)],
        help_text="Cancel more than this far ahead and the deposit is returned in full.",
    )
    #: Percentage of the *deposit* kept when a customer cancels inside the
    #: window. 50 is the industry default; 0 means a late cancellation still
    #: refunds everything, which is a legitimate choice.
    late_cancel_fee_percent = models.PositiveSmallIntegerField(
        default=50,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Of the deposit, not the total. Charged on a late customer cancellation.",
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
        moment = moment or self.local_now()
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

        Reads the prefetch cache when there is one. `.filter()` would ignore it
        and hit the database — and this is called once per slot per slot per
        provider, which turned a single search request into a thousand queries.
        """
        prefetched = getattr(self, "_prefetched_objects_cache", {}).get("hours")
        if prefetched is not None:
            return next((row for row in prefetched if row.weekday == weekday), None)

        return self.hours.filter(weekday=weekday).first()

    def is_open_on(self, weekday: int) -> bool:
        hours = self.hours_for(weekday)
        if hours is None:
            # Monday to Saturday by default. A barber's shop that is shut on
            # Sunday is the exception, not the rule.
            return weekday != 6
        return not hours.is_closed

    def tz(self):
        """This shop's zone, resolved as far down a chain as it goes.

        Shop, then the account, then the server. A missing value must not be
        an exception: a shop that has not set one still has to open.
        """
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        from django.conf import settings

        for name in (
            self.timezone_name,
            getattr(getattr(self, "user", None), "timezone_name", ""),
            settings.TIME_ZONE,
        ):
            if not name:
                continue
            try:
                return ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                # A saved zone that the host no longer knows about — usually an
                # OS database change. Better to fall through than to 500 on
                # every request this shop receives.
                continue

        return ZoneInfo("UTC")

    def local_now(self) -> datetime:
        """The current time where this shop is."""
        return datetime.now(self.tz())

    def localtime(self, moment: datetime) -> datetime:
        """Where ``moment`` falls on this shop's clock."""
        return moment.astimezone(self.tz())

    def ensure_slug(self) -> str:
        """Give this shop an address, and never hand the same one to two shops.

        Called on save rather than by a signal, because a slug that only
        exists once a second thing has run is a slug that is missing when
        somebody reads the row directly.
        """
        if self.slug:
            return self.slug

        base = slugify(self.display_name)[:60] or "shop"
        candidate = base
        suffix = 2

        while ProviderProfile.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
            candidate = f"{base}-{suffix}"
            suffix += 1

        self.slug = candidate
        return candidate

    def save(self, *args, **kwargs):
        self.ensure_slug()
        return super().save(*args, **kwargs)

    def headcount(self) -> int:
        """How many people can be in the chairs at once.

        Derived from the staff rows, with the old ``employee_count`` as the
        fallback for a shop that has not set any up. Two sources of truth for
        capacity is how two simultaneous bookings become three, so the rows
        win as soon as any exist.

        Reads a ``named_staff`` annotation when the queryset supplied one. A
        list view computing "next available" per row would otherwise issue one
        COUNT per shop — the exact N+1 that turned a 20-row page into 1600
        queries once already. Annotate it rather than letting the fallback
        fire per row.
        """
        named = getattr(self, "named_staff", None)
        if named is None:
            named = self.staff.filter(is_active=True).count()
        return named or max(self.employee_count, 1)

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

    #: Percentage of the booking total taken up front, to secure the slot.
    #: Zero means pay in full at booking, which is what most services want.
    #: A long colouring job that empties a chair for three hours is where this
    #: earns its keep — see the deposit research in TODOS.md P1.1.
    deposit_percent = models.PositiveSmallIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Taken at booking; the balance is paid on arrival. 0 means pay in full.",
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


class Staff(TimeStampedModel):
    """A person who works at a shop.

    ``employee_count`` was an integer, so a shop with four barbers was
    "capacity 4" and no booking could ever name one of them. That is the first
    thing a customer asks for — "can I book with Ravi?" — and every competitor
    answers it.

    Deactivated rather than deleted. A booking made six months ago still names
    the person who did it, and a hard delete would either orphan that or take
    the history with it. ``is_active`` is the whole lifecycle: an inactive
    member keeps their name and their bookings but stops appearing in the
    booking flow and stops counting towards capacity.

    ``is_placeholder`` marks a row created by the migration from
    ``employee_count``. Those exist only to carry headcount across the change;
    the provider is told to name them.
    """

    provider = models.ForeignKey(ProviderProfile, on_delete=models.CASCADE, related_name="staff")

    name = models.CharField(max_length=120)
    bio = models.TextField(blank=True, default="")
    photo = models.ImageField(upload_to="staff/", blank=True, null=True)

    is_active = models.BooleanField(default=True, db_index=True)
    is_placeholder = models.BooleanField(
        default=False,
        help_text="Created from the old employee_count. Name it to clear the prompt.",
    )

    class Meta:
        db_table = "providers_staff"
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "name"], name="providers_staff_provider_name_uniq"
            ),
            models.CheckConstraint(condition=~Q(name=""), name="providers_staff_name_not_blank"),
        ]

    def __str__(self) -> str:
        return self.name

    def hours_for(self, weekday: int) -> StaffWorkingHours | None:
        return self.hours.filter(weekday=weekday).first()

    def is_open_on(self, weekday: int) -> bool:
        """Whether this person works on a weekday.

        No row means the shop never set per-person hours, so the person follows
        the shop. Falling back to "closed on Sunday" matches what a shop with
        no Sunday hours means by it.
        """
        hours = self.hours_for(weekday)
        if hours is not None:
            return not hours.is_closed
        return self.provider.is_open_on(weekday)

    def day_bounds(self, weekday: int) -> tuple[time, time] | None:
        """Their own hours for a weekday, or the shop's if they set none."""
        hours = self.hours_for(weekday)
        if hours is not None:
            if hours.is_closed:
                return None
            return hours.opens_at, hours.closes_at
        return self.provider.day_bounds(weekday)


class StaffWorkingHours(models.Model):
    """Per-weekday hours for one person.

    Separate from :class:`WorkingHours` rather than an optional column on it:
    a person's Tuesday is genuinely different from the shop's Tuesday, and
    "usually the same, except Sundays" cannot be expressed by a nullable field
    on the shop's row.
    """

    staff = models.ForeignKey(Staff, on_delete=models.CASCADE, related_name="hours")

    weekday = models.PositiveSmallIntegerField(
        choices=WorkingHours.WEEKDAYS,
        validators=[MinValueValidator(0), MaxValueValidator(6)],
        help_text="0 = Monday. Django's date.weekday() convention.",
    )
    is_closed = models.BooleanField(default=False)
    opens_at = models.TimeField(default="09:00")
    closes_at = models.TimeField(default="20:00")

    class Meta:
        db_table = "providers_staffworkinghours"
        ordering = ["weekday"]
        constraints = [
            models.UniqueConstraint(
                fields=["staff", "weekday"], name="providers_staffhours_staff_weekday_uniq"
            ),
            models.CheckConstraint(
                condition=Q(is_closed=True) | Q(opens_at__lt=F("closes_at")),
                name="providers_staffhours_closes_after_opens",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.staff.name} {self.get_weekday_display()}"
