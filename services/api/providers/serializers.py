"""Serializers for providers, their service menu and their payout account."""

from __future__ import annotations

from django.contrib.gis.geos import Point
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from accounts.serializers import PointFieldSerializer, PublicUserSerializer
from providers.models import ProviderPayout, ProviderProfile, Service, ServiceType

# Coarse enough to be useful for "is this near me", fine enough that a walk-in
# does not land at the wrong shop. The old API returned exact coordinates from
# `getbarber/<pk>` to any authenticated user.
APPROXIMATE_PRECISION = 3


class ServiceSerializer(serializers.ModelSerializer):
    price_display = serializers.CharField(read_only=True)
    duration_minutes = serializers.IntegerField(required=False, min_value=5, max_value=600)

    class Meta:
        model = Service
        fields = [
            "id",
            "name",
            "description",
            "price",
            "price_display",
            "duration_minutes",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "price_display"]

    def validate_price(self, value: int) -> int:
        if value <= 0:
            raise serializers.ValidationError("A price has to be greater than zero.")
        if value > 10_000_000:  # ₹1,00,000
            raise serializers.ValidationError("That price looks too high. Check the amount.")
        return value


@extend_schema_serializer(component_name="ProviderList")
class ProviderListSerializer(serializers.ModelSerializer):
    """A provider as a customer browsing sees them.

    Coordinates are deliberately rounded. A customer needs enough precision to
    see "1.2 km away", not a six-decimal fix on the shop's front door.
    """

    owner = PublicUserSerializer(source="user", read_only=True)
    service_type_label = serializers.CharField(source="get_service_type_display", read_only=True)
    starting_price_display = serializers.CharField(read_only=True)
    approximate_location = serializers.SerializerMethodField()
    is_open_now = serializers.SerializerMethodField()
    next_available = serializers.SerializerMethodField()

    class Meta:
        model = ProviderProfile
        fields = [
            "id",
            "display_name",
            "description",
            "service_type",
            "service_type_label",
            "photo",
            "cover_photo",
            "address",
            "approximate_location",
            "is_open_now",
            "next_available",
            "opening_time",
            "closing_time",
            "employee_count",
            "requires_approval",
            "rating_average",
            "rating_count",
            "starting_price_display",
            "owner",
            "created_at",
        ]
        read_only_fields = fields

    def get_approximate_location(self, obj: ProviderProfile) -> dict | None:
        if not obj.coords:
            return None
        rounded = Point(
            round(obj.coords.x, APPROXIMATE_PRECISION),
            round(obj.coords.y, APPROXIMATE_PRECISION),
            srid=4326,
        )
        # Rounding to three decimal places is ~111 m of slack: enough to render a
        # map marker, not enough to identify the exact counter in a shop.
        return {"latitude": rounded.y, "longitude": rounded.x, "precision_meters": 111}

    def get_is_open_now(self, obj: ProviderProfile) -> bool:
        return obj.is_open_at()

    def get_next_available(self, obj: ProviderProfile) -> str | None:
        from bookings.models import next_free_slot

        slot = next_free_slot(obj)
        return slot.isoformat() if slot else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # `Distance` is a Django expression object, not a number, until it has
        # been resolved. `.m` forces the conversion (metres -> miles-aware value).
        distance = getattr(instance, "distance_metres", None)
        if distance is not None:
            data["distance_km"] = round(float(distance.m) / 1000, 1)
        return data


class ProviderDetailSerializer(ProviderListSerializer):
    """One provider in full, with the menu and their opening hours."""

    services = ServiceSerializer(many=True, read_only=True)
    active_service_count = serializers.SerializerMethodField()
    accepts_bookings = serializers.SerializerMethodField()

    class Meta(ProviderListSerializer.Meta):
        fields = [
            *ProviderListSerializer.Meta.fields,
            "services",
            "active_service_count",
            "accepts_bookings",
            "contact_phone",
            "slot_interval_minutes",
        ]
        read_only_fields = fields

    def get_active_service_count(self, obj: ProviderProfile) -> int:
        return obj.services.filter(is_active=True).count()

    def get_accepts_bookings(self, obj: ProviderProfile) -> bool:
        return obj.is_accepting_bookings and obj.active_service_count > 0


class ProviderSelfSerializer(serializers.ModelSerializer):
    """The provider's own record, including the fields customers never see."""

    owner = PublicUserSerializer(source="user", read_only=True)
    services = ServiceSerializer(many=True, read_only=True)
    # Required, so a shop cannot be saved without a location. Partial updates
    # bypass the required check, so this does not break PATCH.
    coords = PointFieldSerializer()
    starting_price_display = serializers.CharField(read_only=True)
    payout_registered = serializers.SerializerMethodField()

    class Meta:
        model = ProviderProfile
        fields = [
            "id",
            "display_name",
            "description",
            "service_type",
            "photo",
            "cover_photo",
            "address",
            "coords",
            "contact_phone",
            "employee_count",
            "opening_time",
            "closing_time",
            "slot_interval_minutes",
            "is_accepting_bookings",
            "requires_approval",
            "rating_average",
            "rating_count",
            "starting_price_display",
            "services",
            "owner",
            "payout_registered",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "rating_average",
            "rating_count",
            "payout_registered",
            "created_at",
            "updated_at",
        ]

    def get_payout_registered(self, obj: ProviderProfile) -> bool:
        return hasattr(obj, "payout")

    def validate_opening_time(self, value):
        instance = getattr(self, "instance", None)
        if instance and value >= instance.closing_time:
            raise serializers.ValidationError("Closing time has to be after opening time.")
        return value

    def validate_closing_time(self, value):
        instance = getattr(self, "instance", None)
        if instance and value <= instance.opening_time:
            raise serializers.ValidationError("Closing time has to be after opening time.")
        return value


class ProviderWriteSerializer(ProviderSelfSerializer):
    """Create or update a shop.

    ``coords`` arrives as ``{latitude, longitude}`` and has to become a
    ``Point`` before it reaches the model. Doing that in the serializer means
    the view never has to touch request data directly.
    """

    class Meta(ProviderSelfSerializer.Meta):
        fields = [
            field
            for field in ProviderSelfSerializer.Meta.fields
            if field not in {"services", "owner", "starting_price_display"}
        ]
        # Everything except the three fields a shop genuinely cannot be without
        # has a model default. Blanket `required=False` here would let a shop be
        # created with no location and fail at the database instead of at
        # validation, as a bare NOT NULL violation.
        extra_kwargs = {
            name: {"required": False}
            for name in fields
            if name not in {"coords", "display_name", "service_type"}
        } | {"service_type": {"required": True}}

    def validate_coords(self, value):
        if not value:
            raise serializers.ValidationError("A shop needs a location.")
        return value

    @staticmethod
    def to_point(coords: dict | None):
        if not coords:
            return None
        return Point(coords["longitude"], coords["latitude"], srid=4326)

    def create(self, validated_data: dict) -> ProviderProfile:
        coords = validated_data.pop("coords", None)
        validated_data["user"] = self.context["request"].user
        profile = ProviderProfile(coords=self.to_point(coords), **validated_data)
        profile.save()
        return profile

    def update(self, instance: ProviderProfile, validated_data: dict) -> ProviderProfile:
        coords = validated_data.pop("coords", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        point = self.to_point(coords)
        if point is not None:
            instance.coords = point
        instance.save()
        return instance


class PayoutSerializer(serializers.ModelSerializer):
    """Provider payout account.

    Account number and IFSC code are write-only and read back masked. The old
    ``BankDetailsSerializer`` used ``fields='__all__'`` and handed the full
    account number to any authenticated caller who asked.
    """

    account_number = serializers.CharField(write_only=True, required=False, max_length=34)
    ifsc_code = serializers.CharField(write_only=True, required=False, max_length=11)
    account_number_masked = serializers.CharField(read_only=True)
    ifsc_code_masked = serializers.CharField(read_only=True)
    is_verified = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProviderPayout
        fields = [
            "business_name",
            "business_type",
            "beneficiary_name",
            "account_type",
            "account_number",
            "ifsc_code",
            "account_number_masked",
            "ifsc_code_masked",
            "verification_status",
            "is_verified",
            "rejection_reason",
            "razorpay_account_id",
            "updated_at",
        ]
        read_only_fields = [
            "verification_status",
            "is_verified",
            "rejection_reason",
            "razorpay_account_id",
            "updated_at",
        ]
        extra_kwargs = {
            "business_name": {"required": False},
            "beneficiary_name": {"required": False},
        }

    def validate_ifsc_code(self, value: str) -> str:
        value = value.upper().replace(" ", "")
        if len(value) != 11 or not value[:4].isalpha() or not value[4:].isalnum():
            raise serializers.ValidationError("That does not look like a valid IFSC code.")
        return value

    def validate_account_number(self, value: str) -> str:
        digits = value.replace(" ", "").replace("-", "")
        if not digits.isdigit():
            raise serializers.ValidationError("Enter a valid account number.")
        if not 6 <= len(digits) <= 20:
            raise serializers.ValidationError("An account number is 6 to 20 digits.")
        return digits

    def create(self, validated_data: dict) -> ProviderPayout:
        validated_data["provider"] = self.context["provider"]
        payout = ProviderPayout(**validated_data)
        payout.save()
        return payout

    def update(self, instance: ProviderPayout, validated_data: dict) -> ProviderPayout:
        # Changing the account re-opens verification; the new details have not
        # been seen by the payment processor.
        if {"account_number", "ifsc_code"} & validated_data.keys():
            instance.verification_status = ProviderPayout.VerificationStatus.PENDING
            instance.rejection_reason = ""
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        return instance


class ProviderSummarySerializer(serializers.ModelSerializer):
    """The smallest useful provider shape — for embedding in a booking."""

    class Meta:
        model = ProviderProfile
        fields = ["id", "display_name", "service_type", "photo", "rating_average"]
        read_only_fields = fields


def service_type_choices() -> list[dict]:
    return [{"value": value, "label": label} for value, label in ServiceType.choices]
