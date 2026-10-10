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
from rest_framework import serializers

from bookings.models import (
    Booking,
    BookingItem,
    BookingStatus,
    has_room,
    is_within_working_hours,
)
from core.exceptions import BusinessRuleViolation
from core.money import CURRENCY, compute_platform_fee, format_minor
from providers.models import ProviderProfile, Service
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


class BookingSerializer(serializers.ModelSerializer):
    items = BookingItemSerializer(many=True, read_only=True)
    provider = ProviderSummarySerializer(read_only=True)
    customer = serializers.SerializerMethodField()
    total_display = serializers.CharField(read_only=True)
    subtotal_display = serializers.SerializerMethodField()
    platform_fee_display = serializers.SerializerMethodField()
    duration_minutes = serializers.IntegerField(read_only=True)
    can_be_cancelled = serializers.BooleanField(read_only=True)
    is_paid = serializers.BooleanField(read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "reference",
            "provider",
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
            "notes",
            "items",
            "can_be_cancelled",
            "is_paid",
            "cancelled_at",
            "cancellation_reason",
            "created_at",
        ]
        read_only_fields = fields

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
        if not has_room(provider, starts_at, ends_at):
            raise BusinessRuleViolation("That slot is already taken. Pick another time.")

        attrs["provider_obj"] = provider
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

        status = (
            BookingStatus.AWAITING_CONFIRMATION
            if provider.requires_approval
            else BookingStatus.PENDING_PAYMENT
        )

        with transaction.atomic():
            booking = Booking.objects.create(
                customer=self.context["request"].user,
                provider=provider,
                starts_at=starts_at,
                ends_at=ends_at,
                status=status,
                subtotal=subtotal,
                platform_fee=platform_fee,
                total=subtotal + platform_fee,
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
