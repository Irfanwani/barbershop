"""Bookings between a customer and a provider.

Two ideas carry the weight here.

**The server prices the booking.** A booking request names service ids. The API
looks up each service, computes the total, and stores it. A client that sends
its own number is ignored. See
[ADR 0003](../../../docs/decisions/0003-server-authoritative-pricing.md).

**Line items snapshot their price.** ``BookingItem`` copies the service name and
unit price at the moment of booking, so raising prices tomorrow does not
retroactively change yesterday's invoice. The old schema stored
``services`` as a pipe-delimited string — unqueryable, no foreign keys, capped
at 1000 characters — and a single mutable ``totalcost``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Count, F, Q
from django.utils import timezone

from accounts.models import User
from core import references
from core.models import TimeStampedModel
from core.money import CURRENCY, format_minor
from payments.choices import PaymentKind
from providers.models import ProviderProfile, Service, Staff

REFERENCE_PREFIX = references.BOOKING


def generate_reference() -> str:
    """A short booking reference, e.g. ``BK-7QK4M2``."""
    return references.generate_reference(REFERENCE_PREFIX)


class BookingStatus(models.TextChoices):
    """Booking lifecycle.

    The old boolean pair (``paid``, plus a row deleted on cancel) could not
    distinguish "customer cancelled" from "provider cancelled", and left no
    record of a cancellation at all.
    """

    PENDING_PAYMENT = "pending_payment", "Awaiting payment"
    AWAITING_CONFIRMATION = "awaiting_confirmation", "Awaiting provider confirmation"
    CONFIRMED = "confirmed", "Confirmed"
    COMPLETED = "completed", "Completed"
    CANCELLED_BY_CUSTOMER = "cancelled_by_customer", "Cancelled by customer"
    CANCELLED_BY_PROVIDER = "cancelled_by_provider", "Cancelled by provider"
    NO_SHOW = "no_show", "No show"
    REFUNDED = "refunded", "Refunded"
    EXPIRED = "expired", "Expired"

    @property
    def is_terminal(self) -> bool:
        return self in {
            BookingStatus.COMPLETED,
            BookingStatus.CANCELLED_BY_CUSTOMER,
            BookingStatus.CANCELLED_BY_PROVIDER,
            BookingStatus.NO_SHOW,
            BookingStatus.REFUNDED,
            BookingStatus.EXPIRED,
        }

    @property
    def is_cancelled(self) -> bool:
        return self in {
            BookingStatus.CANCELLED_BY_CUSTOMER,
            BookingStatus.CANCELLED_BY_PROVIDER,
        }


#: Statuses that occupy a time slot and so block other bookings.
BLOCKING_STATUSES = (
    BookingStatus.PENDING_PAYMENT,
    BookingStatus.AWAITING_CONFIRMATION,
    BookingStatus.CONFIRMED,
    BookingStatus.COMPLETED,
)


class Booking(TimeStampedModel):
    """One appointment.

    ``starts_at`` is stored in UTC. The old implementation trusted a
    ``currentdatetime`` string sent by the phone to decide whether a slot was in
    the past — so setting the clock forward let you book yesterday.
    """

    reference = models.CharField(
        max_length=16, unique=True, db_index=True, default=generate_reference
    )

    customer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="bookings",
        limit_choices_to={"role": "customer"},
    )
    provider = models.ForeignKey(ProviderProfile, on_delete=models.CASCADE, related_name="bookings")

    #: Which person does this booking, when the shop has named its staff.
    #: Nullable because a shop with no staff rows can still take bookings, and
    #: because PROTECT is the wrong instinct for history: a booking made six
    #: months ago must keep naming the person who did it. Staff are
    #: deactivated, never deleted, so this FK is never cascaded.
    staff = models.ForeignKey(
        "providers.Staff",
        on_delete=models.PROTECT,
        related_name="bookings",
        null=True,
        blank=True,
    )

    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()

    status = models.CharField(
        max_length=32, choices=BookingStatus.choices, default=BookingStatus.PENDING_PAYMENT
    )

    # Computed server-side by core.money.quote. Never read from the request.
    subtotal = models.PositiveIntegerField(default=0)
    platform_fee = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default=CURRENCY)

    notes = models.TextField(blank=True, default="", max_length=500)

    #: The series this appointment is one of, if any. Null for the ones that
    #: are just a booking, which is nearly all of them.
    series = models.ForeignKey(
        "bookings.BookingSeries",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookings",
    )
    #: Which occurrence, counting from zero at the series' start. Unique within
    #: a series, so a task that runs twice cannot create the same week twice.
    occurrence_index = models.PositiveSmallIntegerField(null=True, blank=True)

    #: What must be paid now to secure the slot, and what is owed on arrival.
    #: Frozen here, like the prices: a shop raising its deposit policy next week
    #: must not change what somebody agreed to pay today.
    deposit = models.PositiveIntegerField(default=0)
    balance = models.PositiveIntegerField(default=0)

    #: The shop's cancellation policy as it stood when this booking was made.
    #: Read live, a shop could tighten its window and the customer who booked
    #: last month would find out they now owe money.
    cancellation_window_hours = models.PositiveSmallIntegerField(default=24)
    late_cancel_fee_percent = models.PositiveSmallIntegerField(default=50)
    #: Amount the platform keeps when a customer cancels late. Computed once at
    #: booking time from the deposit, because that is the only figure both sides
    #: agreed to.
    late_cancel_fee = models.PositiveIntegerField(default=0)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=200, blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)

    # Set by the reminder task. Without it, the task cannot tell "not reminded
    # yet" from "reminded and the user ignored it", so it would send the same
    # reminder every fifteen minutes for a week.
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bookings_booking"
        ordering = ["-starts_at"]
        indexes = [
            models.Index(fields=["provider", "starts_at"]),
            models.Index(fields=["customer", "-starts_at"]),
            models.Index(fields=["status"]),
            # Drives the reminder scan: confirmed, unsent, starting soon.
            models.Index(fields=["status", "starts_at", "reminder_sent_at"]),
            models.Index(fields=["provider", "status", "starts_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")), name="bookings_ends_after_starts"
            ),
            # What this actually has to guarantee is that the customer is
            # never charged more than the items plus the fee, and never a
            # negative amount. The old rule — total >= subtotal — read as if
            # the total could never be below the menu price, which is exactly
            # what a discount is, so the first promo code made a legitimate
            # booking impossible to save.
            models.CheckConstraint(condition=Q(total__gte=0), name="bookings_total_not_negative"),
            models.CheckConstraint(
                condition=Q(total__lte=F("subtotal") + F("platform_fee")),
                name="bookings_total_within_items_plus_fee",
            ),
            # A week can only be in a series once, however many times the
            # materialising task runs. Two bookings for the same occurrence
            # would be two charges for one appointment.
            models.UniqueConstraint(
                fields=["series", "occurrence_index"],
                name="bookings_series_occurrence_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} · {self.customer} @ {self.provider} · {self.starts_at:%Y-%m-%d %H:%M}"

    @property
    def duration_minutes(self) -> int:
        return int((self.ends_at - self.starts_at).total_seconds() // 60)

    @property
    def total_display(self) -> str:
        return format_minor(self.total, self.currency)

    @property
    def can_be_cancelled(self) -> bool:
        return self.status not in {
            BookingStatus.COMPLETED,
            BookingStatus.CANCELLED_BY_CUSTOMER,
            BookingStatus.CANCELLED_BY_PROVIDER,
            BookingStatus.REFUNDED,
            BookingStatus.EXPIRED,
            BookingStatus.NO_SHOW,
        }

    @property
    def amount_paid(self) -> int:
        """Net of refunds: what this booking has actually kept.

        Refunds come *out*. Counting a partially-refunded payment as its full
        amount made `is_paid` true and `amount_due` zero while money had
        already gone back — the customer looked fully paid and the shop saw no
        balance due. Never negative, in case a payment is over-refunded by a
        gateway-side adjustment.
        """
        return max(
            sum(
                payment.amount - (payment.refunded_amount or 0)
                for payment in self.payments.all()
                if payment.is_captured
            ),
            0,
        )

    @property
    def is_paid(self) -> bool:
        """Whether nothing more is owed.

        Derived from what has actually been captured against the total, not from
        any status flag: `balance` is a frozen snapshot from booking time and
        does not change when the balance is later paid.

        Not "has any payment been captured" either — that would let a captured
        deposit read as a paid booking, which is exactly the confusion deposits
        create if you are not careful.
        """
        return self.amount_paid >= self.total

    @property
    def amount_due(self) -> int:
        """What is still outstanding, in the smallest currency unit.

        Derived rather than stored, so it cannot drift from what was actually
        captured. Never negative: a booking cannot owe the customer money.
        """
        return max(self.total - self.amount_paid, 0)

    @property
    def requires_deposit(self) -> bool:
        return self.deposit > 0 and not self.has_captured_deposit

    @property
    def has_captured_deposit(self) -> bool:
        """Whether a deposit is actually held.

        A deposit that was refunded is not money we have. Counting it as
        captured made `requires_deposit` false on a booking whose deposit had
        been handed straight back, so the shop was never asked for it again.
        """
        return any(
            payment.is_captured
            and payment.kind == PaymentKind.DEPOSIT
            and payment.refunded_amount < payment.amount
            for payment in self.payments.all()
        )

    @property
    def cancellation_deadline(self) -> datetime:
        """The last moment a customer can cancel without a fee."""
        return self.starts_at - timedelta(hours=self.cancellation_window_hours)

    def is_late_cancellation(self, *, at: datetime | None = None) -> bool:
        """Whether cancelling now would incur a fee.

        A zero window means "no free window": any cancellation forfeits the
        deposit, which is what a shop that insists on full prepayment wants.
        The opposite — always refundable — is expressed with
        ``late_cancel_fee_percent = 0``, so both directions are reachable
        without a second setting.

        Only ever meaningful for the customer. A provider cancelling is always
        free — the shop has the chair and the customer is not at fault.
        """
        if self.cancellation_window_hours == 0:
            return True
        moment = at or timezone.now()
        return moment >= self.cancellation_deadline

    def minutes_until_start(self) -> int:
        return int((self.starts_at - timezone.now()).total_seconds() // 60)


class BookingItem(TimeStampedModel):
    """One line of a booking, with the price frozen at the time of booking.

    ``service`` is nullable and set to ``NULL`` when a service is deleted, so
    deleting a menu item does not destroy the financial record of an appointment
    that already used it.
    """

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="items")

    service = models.ForeignKey(
        Service, on_delete=models.SET_NULL, null=True, blank=True, related_name="booking_items"
    )

    # Snapshots. These are the authoritative record of what was agreed.
    name = models.CharField(max_length=100)
    unit_price = models.PositiveIntegerField(help_text="In the smallest currency unit.")
    quantity = models.PositiveSmallIntegerField(default=1)
    duration_minutes = models.PositiveSmallIntegerField(default=30)

    class Meta:
        db_table = "bookings_booking_item"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1), name="bookings_item_quantity_gte_1"
            )
        ]

    def __str__(self) -> str:
        return f"{self.quantity} × {self.name} @ {format_minor(self.unit_price)}"  # noqa: RUF001

    @property
    def line_total(self) -> int:
        return self.unit_price * self.quantity


class SlotAvailability(models.Model):
    """Pre-computed answer to "is this slot free?".

    Not a source of truth — :meth:`Booking.is_slot_available` still re-checks at
    write time, because caching a booking decision invites double-booking. This
    exists so the provider's calendar screen does not run a range query per slot
    of the day.
    """

    provider = models.ForeignKey(ProviderProfile, on_delete=models.CASCADE, related_name="slots")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    is_available = models.BooleanField(default=True)
    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="+", null=True, blank=True
    )

    class Meta:
        db_table = "bookings_slot_availability"
        indexes = [models.Index(fields=["provider", "starts_at"])]

    def __str__(self) -> str:
        return f"{self.provider_id} @ {self.starts_at:%Y-%m-%d %H:%M} ({'free' if self.is_available else 'taken'})"


def default_booking_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """The bookable window: from the next half hour, for the next 30 days."""
    now = now or timezone.now()
    start = (now + timedelta(minutes=29)).replace(second=0, microsecond=0)
    start += timedelta(minutes=(30 - start.minute) % 30)
    return start, start + timedelta(days=30)


def has_room(
    provider: ProviderProfile,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking: int | None = None,
    staff: Staff | None = None,
) -> bool:
    """Whether the provider can take one more booking over this interval.

    Capacity-aware: a shop with three barbers can run three simultaneous
    bookings, so "does this overlap anything?" is not the question. Half-open
    intervals, so a booking ending exactly when the next begins is not a
    conflict — which is what a customer expects when booking back-to-back.

    Naming a staff member adds a second, stricter question. The shop having a
    free chair is not enough if it is *their* chair they would be sitting in.
    """
    overlapping = Booking.objects.filter(
        provider=provider,
        status__in=BLOCKING_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    if exclude_booking:
        overlapping = overlapping.exclude(pk=exclude_booking)
    # A slot held for a waitlist offer is taken, even though no booking exists
    # for it yet. "First to reply gets the slot" is only true if the seconds
    # between the offer and the reply belong to one person.
    held = overlapping_slot_holds(provider, starts_at, ends_at)

    if overlapping.count() + held["total"] >= provider.headcount():
        return False

    if staff is None:
        return True

    if Booking.objects.filter(
        provider=provider,
        staff=staff,
        status__in=BLOCKING_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).exists():
        return False

    # Someone holding a slot for this specific barber is not available either.
    return held["staff"] == 0


def overlapping_slot_holds(
    provider: ProviderProfile, starts_at: datetime, ends_at: datetime
) -> dict[str, int]:
    """How many active waitlist holds cover this interval.

    Split by whether the hold is for a named barber, because a chair held for
    someone specific cannot be given to someone else, while a chair held for
    whoever is free just reduces the total.
    """
    active = SlotHold.objects.filter(
        provider=provider,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
        offer__status="pending",
        offer__expires_at__gt=timezone.now(),
    )
    totals = active.aggregate(total=Count("pk"), staff=Count("pk", filter=Q(staff__isnull=False)))
    return {"total": totals["total"] or 0, "staff": totals["staff"] or 0}


def is_slot_available(
    provider: ProviderProfile,
    starts_at: datetime,
    ends_at: datetime,
    *,
    exclude_booking: int | None = None,
) -> bool:
    """Whether *nothing at all* overlaps this interval.

    Stricter than :func:`has_room`. Use this when the slot is single-occupancy
    by nature (a treatment room, one chair); use :func:`has_room` for anything
    that scales with headcount.
    """
    conflicts = Booking.objects.filter(
        provider=provider,
        status__in=BLOCKING_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    if exclude_booking:
        conflicts = conflicts.exclude(pk=exclude_booking)
    return not conflicts.exists()


def provider_has_capacity(
    provider: ProviderProfile, starts_at: datetime, ends_at: datetime
) -> bool:
    """Whether the shop has a free chair at that time.

    A provider with four employees can run four simultaneous bookings. The old
    check compared a round-tripped timestamp string against ``employee_count``
    and silently swallowed every exception with ``except: pass`` — so any error
    in that comparison meant "always allow", i.e. double-booking by default.
    """
    overlapping = Booking.objects.filter(
        provider=provider,
        status__in=BLOCKING_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).count()
    return overlapping < provider.headcount()


def slot_grid(provider: ProviderProfile, days: int = 14) -> list[tuple[datetime, datetime]]:
    """Every bookable interval for the next ``days``, aligned to the slot grid.

    Reads as a schedule, which is what a customer's calendar screen wants.
    """
    step = timedelta(minutes=provider.slot_interval_minutes or 30)
    window_start, window_end = default_booking_window()
    window_end = min(window_end, timezone.now() + timedelta(days=days))

    slots: list[tuple[datetime, datetime]] = []
    cursor = window_start
    while cursor < window_end:
        if is_within_working_hours(provider, cursor, cursor + step):
            slots.append((cursor, cursor + step))
        cursor += step
    return slots


def busy_intervals(provider: ProviderProfile, *, days: int = 7) -> list[tuple[datetime, datetime]]:
    """Every interval already taken, in one query.

    Callers that need to know where the gaps are should fetch the busy periods
    once and walk them, rather than asking the database once per candidate slot.
    A shop with a week of openings has hundreds of slots; the old per-slot query
    turned a single search result into hundreds of round trips.
    """
    window_start, window_end = default_booking_window()
    window_end = min(window_end, timezone.now() + timedelta(days=days))

    return list(
        Booking.objects.filter(
            provider=provider,
            status__in=BLOCKING_STATUSES,
            ends_at__gt=window_start,
            starts_at__lt=window_end,
        )
        .values_list("starts_at", "ends_at")
        .order_by("starts_at")
    )


def next_free_slot(
    provider: ProviderProfile,
    *,
    days: int = 7,
    busy: list[tuple[datetime, datetime]] | None = None,
) -> datetime | None:
    """The soonest interval the provider is free for, or None.

    Pass ``busy`` when you already have the taken intervals — a caller working
    through several providers should fetch them once and reuse.
    """
    capacity = provider.headcount()
    taken = busy_intervals(provider, days=days) if busy is None else busy

    for starts_at, ends_at in slot_grid(provider, days=days):
        if not is_within_working_hours(provider, starts_at, ends_at):
            continue

        # Overlapping is half-open, so a booking ending exactly when this begins
        # is not a conflict. Counting in Python is fine here: this is a list of
        # a few hundred intervals, not a query per slot.
        overlapping = sum(
            1 for taken_start, taken_end in taken if taken_start < ends_at and taken_end > starts_at
        )
        if overlapping < capacity:
            return starts_at

    return None


def is_within_working_hours(
    provider: ProviderProfile, starts_at: datetime, ends_at: datetime
) -> bool:
    """Whether this shop is open for the whole interval.

    Consults the per-weekday hours first and falls back to the shop's single
    opening/closing pair when it has none. A closed weekday produces no slots at
    all, which is the point of the toggle: the shop is off.
    """
    # The shop's clock, not the server's. These are naive local times because
    # a barber says "I open at nine" and means nine where they work.
    local_start = provider.localtime(starts_at)
    local_end = provider.localtime(ends_at)

    # A booking that runs over midnight is not a haircut; it is a bug in whatever
    # produced it, and admitting it would show the shop as open for 24 hours.
    if local_start.date() != local_end.date():
        return False

    bounds = provider.day_bounds(local_start.weekday())
    if bounds is None:
        return False
    opens_at, closes_at = bounds

    return opens_at <= local_start.time() and local_end.time() <= closes_at


AUTH_USER_MODEL = settings.AUTH_USER_MODEL


class WaitlistStatus(models.TextChoices):
    WAITING = "waiting", "Waiting"
    #: A slot is being held for this entry and nobody has answered yet.
    OFFERED = "offered", "Offered"
    BOOKED = "booked", "Booked"
    #: They said no, or let the hold run out. Not re-offered the same slot.
    DECLINED = "declined", "Declined"
    LEFT = "left", "Left"


class WaitlistEntry(TimeStampedModel):
    """ "Tell me when something frees up."

    A window rather than a single slot, because the common case is a customer
    who wants "any time this week", not one specific minute. Pinning a single
    time would mean the waitlist misses almost every cancellation, which is the
    one thing it exists for.

    ``staff`` is optional and means "anyone". A shop with three barbers and one
    freed chair should offer it to whoever is waiting, not to the person who
    happens to want a specific one.
    """

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="waitlist_entries"
    )
    provider = models.ForeignKey(
        ProviderProfile, on_delete=models.CASCADE, related_name="waitlist_entries"
    )
    staff = models.ForeignKey(
        "providers.Staff",
        on_delete=models.CASCADE,
        related_name="waitlist_entries",
        null=True,
        blank=True,
    )
    service = models.ForeignKey(
        "providers.Service", on_delete=models.CASCADE, related_name="waitlist_entries"
    )

    window_start = models.DateTimeField()
    window_end = models.DateTimeField()

    status = models.CharField(
        max_length=16, choices=WaitlistStatus.choices, default=WaitlistStatus.WAITING, db_index=True
    )

    class Meta:
        db_table = "bookings_waitlist_entry"
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["provider", "status", "created_at"])]
        constraints = [
            # A window that ends before it starts is a typo, not "any time".
            models.CheckConstraint(
                condition=Q(window_start__lt=F("window_end")),
                name="bookings_waitlist_window_ordered",
            ),
            # One live entry per customer per shop: joining twice would let one
            # person take two offers for the same freed slot.
            models.UniqueConstraint(
                fields=["customer", "provider", "service"],
                condition=Q(status__in=["waiting", "offered"]),
                name="bookings_waitlist_one_live_per_shop",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer} → {self.provider}"

    def matches(self, slot) -> bool:
        """Whether a freed slot is something this entry asked for.

        Shop and service are not re-checked here: the caller has already
        selected entries for that shop and service. What is checked is whether
        this entry actually wanted this *time* — a customer who said "Tuesday
        afternoon" should not be woken at 09:00 on Thursday.
        """
        return self.window_start <= slot.starts_at and slot.ends_at <= self.window_end

    def wants(self, staff) -> bool:
        """Whether this entry is happy with a specific barber.

        ``None`` means whoever is free.
        """
        return self.staff_id is None or (staff is not None and self.staff_id == staff.pk)


class WaitlistOffer(TimeStampedModel):
    """One freed slot, held for one person, for a while.

    The hold is the point. Without it the slot is offered to someone who then
    takes a minute to decide, during which another customer — who has no idea
    any of this is happening — books it. The niche promises "filled in
    seconds"; that only works if the seconds belong to one person.
    """

    entry = models.ForeignKey(WaitlistEntry, on_delete=models.CASCADE, related_name="offers")

    # The freed slot, denormalised. Kept on the offer rather than pointing at a
    # booking, because the booking it came from is cancelled and will be
    # deleted or archived.
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    staff = models.ForeignKey(
        "providers.Staff",
        on_delete=models.CASCADE,
        related_name="waitlist_offers",
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=16,
        choices=[
            ("pending", "Pending"),
            ("accepted", "Accepted"),
            ("declined", "Declined"),
            ("expired", "Expired"),
        ],
        default="pending",
        db_index=True,
    )
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "bookings_waitlist_offer"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(starts_at__lt=F("ends_at")),
                name="bookings_waitlist_offer_slot_ordered",
            ),
        ]

    def __str__(self) -> str:
        return f"offer to {self.entry_id} for {self.starts_at}"

    @property
    def is_active(self) -> bool:
        return self.status == "pending" and self.expires_at > timezone.now()


class SlotHold(models.Model):
    """A slot reserved for one waitlist offer.

    Consulted by the availability checks, so a held slot stops being publicly
    bookable the moment it is offered. Without this an offer is a suggestion
    and "first to reply gets the slot" is a lie.
    """

    offer = models.OneToOneField(WaitlistOffer, on_delete=models.CASCADE, related_name="hold")
    provider = models.ForeignKey(
        ProviderProfile, on_delete=models.CASCADE, related_name="slot_holds"
    )
    staff = models.ForeignKey(
        "providers.Staff",
        on_delete=models.CASCADE,
        related_name="slot_holds",
        null=True,
        blank=True,
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    class Meta:
        db_table = "bookings_slothold"
        indexes = [models.Index(fields=["provider", "starts_at", "ends_at"])]

    def __str__(self) -> str:
        return f"held for offer {self.offer_id}"


class SeriesStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    STOPPED = "stopped", "Stopped"
    FINISHED = "finished", "Finished"


class BookingSeries(TimeStampedModel):
    """A run of appointments booked at once, at a fixed interval.

    "Trims every four weeks, so their next visits are already on the calendar"
    is the pitch. What makes it work rather than merely exist is the interval
    being measured from an **origin**, never from the last occurrence:

    - If the next booking were computed as ``last + interval``, skipping one
      occurrence would slide every later one a week earlier. A customer who
      missed February would find March moved to where February was.
    - Measured from the origin, occurrence *n* is always at
      ``starts_at + n * interval``, so a skipped week is a hole in the series
      rather than a shift of everything after it.

    Each occurrence is an ordinary :class:`Booking` with its own price, deposit
    and cancellation, because it is separately chargeable and a customer who
    misses one must be able to cancel that one alone.
    """

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="booking_series"
    )
    provider = models.ForeignKey(
        "providers.ProviderProfile", on_delete=models.CASCADE, related_name="booking_series"
    )
    staff = models.ForeignKey(
        "providers.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="booking_series",
    )

    #: Occurrence 0. The anchor for every other date in the series.
    starts_at = models.DateTimeField()
    #: Same time of day as ``starts_at``, this many days later.
    interval_days = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(365)]
    )
    #: How many appointments in total, including the first.
    total_occurrences = models.PositiveSmallIntegerField(
        default=4, validators=[MinValueValidator(1), MaxValueValidator(52)]
    )

    status = models.CharField(
        max_length=16, choices=SeriesStatus.choices, default=SeriesStatus.ACTIVE
    )

    #: When the customer stopped it, if they did. Kept so a stopped series is
    #: not silently resurrected by a task that started before the stop landed.
    stopped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bookings_series"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "starts_at"])]

    def __str__(self) -> str:
        return f"{self.customer} every {self.interval_days}d x{self.total_occurrences}"

    @property
    def created_occurrences(self) -> int:
        return self.bookings.count()

    def occurs_at(self, index: int) -> datetime:
        """When occurrence ``index`` is due.

        Always from the origin. See the class docstring for why that is the
        whole point of this model.
        """
        return self.starts_at + timedelta(days=self.interval_days * index)

    def next_index(self, now=None) -> int | None:
        """The next occurrence still worth booking, or ``None`` when finished.

        An occurrence whose moment has passed without a booking is **skipped**,
        not retried. This is what stops a single taken slot from stalling the
        series for good: without it, week one blocks and every later week waits
        behind it forever, and the customer quietly stops turning up.

        Skipping is also why a missed week does not drag the rest earlier.
        Because the remaining dates are still measured from the origin, week two
        lands two intervals in - in the gap, not where week one would have been.
        """
        moment = now or timezone.now()
        taken = set(self.bookings.values_list("occurrence_index", flat=True))
        for index in range(self.total_occurrences):
            if index in taken:
                continue
            if self.occurs_at(index) < moment:
                continue
            return index
        return None

    def skipped_indices(self, *, now=None) -> list[int]:
        """Occurrences whose moment passed with nothing booked. For the log."""
        moment = now or timezone.now()
        taken = set(self.bookings.values_list("occurrence_index", flat=True))
        return [
            index
            for index in range(self.total_occurrences)
            if index not in taken and self.occurs_at(index) < moment
        ]
