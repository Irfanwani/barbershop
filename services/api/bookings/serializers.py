"""Booking serializers.

The important one here is :class:`BookingCreateSerializer`. It accepts service
ids and computes the price; it never accepts a total. See
[ADR 0003](../../../docs/decisions/0003-server-authoritative-pricing.md).
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from bookings.models import (
    Booking,
    BookingItem,
    BookingStatus,
    WaitlistEntry,
    WaitlistOffer,
    WaitlistStatus,
    has_room,
    is_within_working_hours,
)
from core.exceptions import BusinessRuleViolation
from core.money import CURRENCY, compute_deposit, compute_platform_fee, format_minor
from providers.models import ProviderProfile, Service, Staff
from providers.serializers import ProviderSummarySerializer


class BookingItemSerializer(serializers.ModelSerializer):
    """One line of a booking.

    Reads the snapshot, not the live service row: if the provider raises this
    price next month, yesterday's invoice must not change.
    """

    line_total = serializers.IntegerField(read_only=True)
    unit_price_display = serializers.SerializerMethodField()

    class Meta:
        model = BookingItem
        fields = [
            "id",
            "service",
            "name",
            "unit_price",
            "unit_price_display",
            "quantity",
            "duration_minutes",
            "line_total",
        ]
        read_only_fields = fields

    def get_unit_price_display(self, obj: BookingItem) -> str:
        return format_minor(obj.unit_price)


class StaffSummarySerializer(serializers.ModelSerializer):
    """Who is doing the job, on a booking.

    Frozen with the rest of the booking. If the person later leaves the shop
    their name stays on the appointment they worked.
    """

    class Meta:
        model = Staff
        fields = ["id", "name", "photo"]


@extend_schema_serializer(component_name="Booking")
class BookingSerializer(serializers.ModelSerializer):
    items = BookingItemSerializer(many=True, read_only=True)
    provider = ProviderSummarySerializer(read_only=True)
    staff = StaffSummarySerializer(read_only=True)
    customer = serializers.SerializerMethodField()
    total_display = serializers.CharField(read_only=True)
    subtotal_display = serializers.SerializerMethodField()
    platform_fee_display = serializers.SerializerMethodField()
    duration_minutes = serializers.IntegerField(read_only=True)
    can_be_cancelled = serializers.BooleanField(read_only=True)
    is_paid = serializers.BooleanField(read_only=True)
    amount_paid = serializers.IntegerField(read_only=True)
    amount_due = serializers.IntegerField(read_only=True)
    requires_deposit = serializers.BooleanField(read_only=True)
    cancellation_deadline = serializers.DateTimeField(read_only=True)
    is_late_cancellation = serializers.SerializerMethodField()
    late_cancel_fee = serializers.IntegerField(read_only=True)
    late_cancel_fee_display = serializers.SerializerMethodField()
    deposit_display = serializers.SerializerMethodField()
    balance_display = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "reference",
            "provider",
            "staff",
            "customer",
            "status",
            "starts_at",
            "ends_at",
            "duration_minutes",
            "subtotal",
            "subtotal_display",
            "platform_fee",
            "platform_fee_display",
            "total",
            "total_display",
            "currency",
            "deposit",
            "deposit_display",
            "balance",
            "balance_display",
            "amount_paid",
            "amount_due",
            "requires_deposit",
            "cancellation_window_hours",
            "cancellation_deadline",
            "is_late_cancellation",
            "late_cancel_fee",
            "late_cancel_fee_display",
            "notes",
            "items",
            "can_be_cancelled",
            "is_paid",
            "cancelled_at",
            "cancellation_reason",
            "created_at",
        ]
        read_only_fields = fields

    def get_is_late_cancellation(self, obj: Booking) -> bool:
        """Whether cancelling *now* would cost the customer the fee.

        From the customer's side. The provider's view is different and is not
        this field.
        """
        return obj.is_late_cancellation()

    def get_late_cancel_fee_display(self, obj: Booking) -> str:
        return format_minor(obj.late_cancel_fee, obj.currency)

    def get_deposit_display(self, obj: Booking) -> str:
        return format_minor(obj.deposit, obj.currency)

    def get_balance_display(self, obj: Booking) -> str:
        return format_minor(obj.balance, obj.currency)

    def get_customer(self, obj: Booking) -> dict:
        user = obj.customer
        return {"id": user.id, "username": user.username, "display_name": user.display_name}

    def get_subtotal_display(self, obj: Booking) -> str:
        return format_minor(obj.subtotal, obj.currency)

    def get_platform_fee_display(self, obj: Booking) -> str:
        return format_minor(obj.platform_fee, obj.currency)


class BookingListSerializer(BookingSerializer):
    """A booking as it appears in a list — same shape, fewer queries."""

    class Meta(BookingSerializer.Meta):
        pass


class QuoteRequestSerializer(serializers.Serializer):
    """Ask what a booking would cost, before committing to it."""

    provider = serializers.IntegerField()
    services = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    starts_at = serializers.DateTimeField()

    def validate_services(self, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise serializers.ValidationError("The same service was listed twice.")
        return value


class QuoteSerializer(serializers.Serializer):
    """The server's price for a booking.

    The client shows this and asks the customer to agree. A client that sends a
    different number in the booking request is ignored.
    """

    currency = serializers.CharField()
    subtotal = serializers.IntegerField()
    platform_fee = serializers.IntegerField()
    total = serializers.IntegerField()
    duration_minutes = serializers.IntegerField()
    subtotal_display = serializers.CharField()
    platform_fee_display = serializers.CharField()
    total_display = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    items = serializers.ListField(child=serializers.DictField())


class BookingCreateSerializer(serializers.Serializer):
    """Create a booking.

    Accepts ``provider``, ``services`` (ids) and ``starts_at``. The total is
    computed here from :class:`~providers.models.Service` rows, never read from
    the request.

    The old endpoint stored ``request.data['totalcost']`` verbatim, so a client
    could book a 900-rupee haircut for one rupee.
    """

    provider = serializers.IntegerField()
    #: Optional. A shop that has not named its staff takes bookings with this
    #: null, which is the same as it always was.
    staff = serializers.IntegerField(required=False, allow_null=True)
    services = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    starts_at = serializers.DateTimeField()
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")

    MAX_SERVICES = 10

    def validate_services(self, value: list[int]) -> list[int]:
        if len(value) > self.MAX_SERVICES:
            raise serializers.ValidationError(
                f"You can book at most {self.MAX_SERVICES} services in one visit."
            )
        if len(value) != len(set(value)):
            raise serializers.ValidationError("The same service was listed twice.")
        return value

    def validate(self, attrs: dict) -> dict:
        provider = get_object_or_404(ProviderProfile, pk=attrs["provider"])

        if not provider.is_bookable:
            raise BusinessRuleViolation("This provider is not taking bookings right now.")

        services = list(
            Service.objects.filter(
                pk__in=attrs["services"], provider=provider, is_active=True
            ).select_related("provider")
        )
        if len(services) != len(attrs["services"]):
            # Either an id does not exist, or it belongs to a different provider,
            # or it is retired. All three are the same answer to the client.
            raise BusinessRuleViolation(
                "One or more of those services is not available from this provider."
            )

        starts_at = attrs["starts_at"]
        duration = timedelta(minutes=sum(service.duration_minutes for service in services))
        ends_at = starts_at + duration

        now = timezone.now()

        # The server's clock, not the client's. The old check used a
        # `currentdatetime` string posted by the phone, so setting the clock
        # forward let you book yesterday.
        if starts_at <= now:
            raise BusinessRuleViolation("That time has already passed. Pick a later slot.")
        if starts_at > now + timedelta(days=90):
            raise BusinessRuleViolation("Bookings can only be made up to 90 days ahead.")

        if not is_within_working_hours(provider, starts_at, ends_at):
            raise BusinessRuleViolation(
                f"{provider.display_name} is open "
                f"{provider.opening_time:%H:%M} to {provider.closing_time:%H:%M}."
            )

        # Capacity, not bare overlap: a shop with four barbers can run four
        # simultaneous bookings.
        staff = None
        if attrs.get("staff") is not None:
            # Scoped to this provider on purpose. "That staff member does not
            # exist" and "that staff member is not ours" have to be the same
            # answer, or the endpoint confirms which shops someone works for.
            staff = Staff.objects.filter(
                pk=attrs["staff"], provider=provider, is_active=True
            ).first()
            if staff is None:
                raise BusinessRuleViolation("That staff member is not available at this shop.")

            if not staff.is_open_on(starts_at.weekday()):
                raise BusinessRuleViolation(f"{staff.name} does not work that day.")

            bounds = staff.day_bounds(starts_at.weekday())
            if bounds is None:
                raise BusinessRuleViolation(f"{staff.name} is not working that day.")
            opens_at, closes_at = bounds
            local = timezone.localtime(starts_at)
            if not (opens_at <= local.time() and local.time() < closes_at):
                raise BusinessRuleViolation(
                    f"{staff.name} works {opens_at:%H:%M} to {closes_at:%H:%M} on that day."
                )

        if not has_room(provider, starts_at, ends_at, staff=staff):
            raise BusinessRuleViolation("That slot is already taken. Pick another time.")

        attrs["provider_obj"] = provider
        attrs["staff_obj"] = staff
        attrs["service_objs"] = services
        attrs["ends_at"] = ends_at
        return attrs

    def save(self, **kwargs) -> Booking:
        provider: ProviderProfile = self.validated_data["provider_obj"]
        services: list[Service] = self.validated_data["service_objs"]
        starts_at = self.validated_data["starts_at"]
        ends_at = self.validated_data["ends_at"]

        subtotal = sum(service.price for service in services)
        platform_fee = compute_platform_fee(subtotal, settings.PLATFORM_FEE_PERCENT)
        total = subtotal + platform_fee

        # The strictest requirement across the basket. A customer booking a
        # colour service and a trim has agreed to the colour service's deposit;
        # taking the average would under-charge the shop on the thing that
        # actually costs them the chair time.
        deposit_percent = max((service.deposit_percent for service in services), default=0)
        deposit, balance = compute_deposit(total, deposit_percent)

        # The late-cancel fee is a slice of the *deposit*, worked out now. Both
        # sides agree to it at booking time; a policy tightened afterwards must
        # not apply to a booking that predates it.
        late_cancel_fee, _ = compute_deposit(deposit, provider.late_cancel_fee_percent)

        status = (
            BookingStatus.AWAITING_CONFIRMATION
            if provider.requires_approval
            else BookingStatus.PENDING_PAYMENT
        )

        with transaction.atomic():
            booking = Booking.objects.create(
                customer=self.context["request"].user,
                provider=provider,
                staff=self.validated_data.get("staff_obj"),
                starts_at=starts_at,
                ends_at=ends_at,
                status=status,
                subtotal=subtotal,
                platform_fee=platform_fee,
                total=total,
                deposit=deposit,
                balance=balance,
                cancellation_window_hours=provider.cancellation_window_hours,
                late_cancel_fee_percent=provider.late_cancel_fee_percent,
                late_cancel_fee=late_cancel_fee,
                currency=CURRENCY,
                notes=self.validated_data.get("notes", ""),
            )
            BookingItem.objects.bulk_create(
                [
                    BookingItem(
                        booking=booking,
                        service=service,
                        name=service.name,
                        unit_price=service.price,
                        quantity=1,
                        duration_minutes=service.duration_minutes,
                    )
                    for service in services
                ]
            )

        return booking


class CancelBookingSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")


class WaitlistEntrySerializer(serializers.ModelSerializer):
    """A waitlist entry, as the customer sees their own."""

    provider_name = serializers.CharField(source="provider.display_name", read_only=True)
    service_name = serializers.CharField(source="service.name", read_only=True)
    staff_name = serializers.CharField(source="staff.name", read_only=True, default=None)

    class Meta:
        model = WaitlistEntry
        fields = [
            "id",
            "provider",
            "provider_name",
            "service",
            "service_name",
            "staff",
            "staff_name",
            "window_start",
            "window_end",
            "status",
            "created_at",
        ]
        read_only_fields = ["status", "created_at", "provider_name", "service_name", "staff_name"]


class WaitlistJoinSerializer(serializers.Serializer):
    """Ask to be told when something frees up."""

    provider = serializers.IntegerField()
    service = serializers.IntegerField()
    staff = serializers.IntegerField(required=False, allow_null=True)
    window_start = serializers.DateTimeField()
    window_end = serializers.DateTimeField()

    def validate(self, attrs: dict) -> dict:
        if attrs["window_start"] >= attrs["window_end"]:
            raise serializers.ValidationError(
                {"window_end": "The end of the window has to be after its start."}
            )

        if attrs["window_start"] <= timezone.now():
            raise serializers.ValidationError({"window_start": "That window has already started."})

        provider = get_object_or_404(ProviderProfile, pk=attrs["provider"])

        service = Service.objects.filter(
            pk=attrs["service"], provider=provider, is_active=True
        ).first()
        if service is None:
            # Same answer as a missing id, so this cannot be used to find out
            # which services another shop offers.
            raise serializers.ValidationError(
                {"service": "That service is not available at this shop."}
            )

        staff = None
        if attrs.get("staff") is not None:
            staff = Staff.objects.filter(
                pk=attrs["staff"], provider=provider, is_active=True
            ).first()
            if staff is None:
                raise serializers.ValidationError(
                    {"staff": "That person does not work at this shop."}
                )

        duplicate = WaitlistEntry.objects.filter(
            customer=self.context["request"].user,
            provider=provider,
            service=service,
            status__in=[WaitlistStatus.WAITING, WaitlistStatus.OFFERED],
        ).exists()
        if duplicate:
            raise serializers.ValidationError(
                "You are already on the waitlist for that service here."
            )

        attrs["provider_obj"] = provider
        attrs["service_obj"] = service
        attrs["staff_obj"] = staff
        return attrs

    def save(self, **kwargs) -> WaitlistEntry:
        return WaitlistEntry.objects.create(
            customer=self.context["request"].user,
            provider=self.validated_data["provider_obj"],
            service=self.validated_data["service_obj"],
            staff=self.validated_data.get("staff_obj"),
            window_start=self.validated_data["window_start"],
            window_end=self.validated_data["window_end"],
        )


class WaitlistOfferSerializer(serializers.ModelSerializer):
    """A slot being held for this customer, and how long they have."""

    shop_name = serializers.CharField(source="entry.provider.display_name", read_only=True)
    service_name = serializers.CharField(source="entry.service.name", read_only=True)
    staff_name = serializers.CharField(source="staff.name", read_only=True, default=None)
    seconds_left = serializers.SerializerMethodField()
    can_accept = serializers.SerializerMethodField()

    class Meta:
        model = WaitlistOffer
        fields = [
            "id",
            "shop_name",
            "service_name",
            "staff_name",
            "starts_at",
            "ends_at",
            "status",
            "expires_at",
            "seconds_left",
            "can_accept",
        ]

    def get_seconds_left(self, obj: WaitlistOffer) -> int:
        return max(0, int((obj.expires_at - timezone.now()).total_seconds()))

    def get_can_accept(self, obj: WaitlistOffer) -> bool:
        """Whether accepting would still succeed.

        The hold may have lapsed without the cleanup task having run, and
        offering a button that will be refused is worse than not offering it.
        """
        return obj.status == "pending" and obj.expires_at > timezone.now()


class WaitlistDeclineResultSerializer(serializers.Serializer):
    """What happened when someone let a held slot go.

    ``passed_on`` is the part worth sending: without it a customer who has
    already declined sits waiting to find out whether anybody took it.
    """

    declined = serializers.BooleanField()
    passed_on = serializers.BooleanField()


class WaitlistDeclineSerializer(serializers.Serializer):
    """Declining takes no arguments — the offer id says which one."""

    class Meta:
        pass


class RescheduleSerializer(serializers.Serializer):
    """Move a booking to a different time.

    ``accept_price_change`` is the customer agreeing to a price that moved
    since they booked. It is a separate, explicit field rather than something
    inferred, because agreeing to more money is not something a client should
    do by omission.
    """

    starts_at = serializers.DateTimeField()
    accept_price_change = serializers.BooleanField(default=False)
