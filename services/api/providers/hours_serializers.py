"""Serializers for a provider's own shop settings."""

from rest_framework import serializers

from providers.models import ProviderProfile, WorkingHours

WEEKDAY_LABELS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


class WorkingHoursSerializer(serializers.ModelSerializer):
    """One weekday of opening hours."""

    opens_at = serializers.TimeField(format="%H:%M", input_formats=["%H:%M"])
    closes_at = serializers.TimeField(format="%H:%M", input_formats=["%H:%M"])
    weekday_label = serializers.CharField(read_only=True)

    class Meta:
        model = WorkingHours
        fields = ["id", "weekday", "weekday_label", "is_closed", "opens_at", "closes_at"]

    def validate(self, attrs):
        """Reject a shift that ends before it starts.

        Checked here rather than only by the database constraint so the provider
        gets a field-level message instead of a 500 from an IntegrityError.
        """
        if attrs.get("is_closed"):
            return attrs

        opens_at = attrs.get("opens_at", getattr(self.instance, "opens_at", None))
        closes_at = attrs.get("closes_at", getattr(self.instance, "closes_at", None))
        if opens_at is not None and closes_at is not None and opens_at >= closes_at:
            raise serializers.ValidationError(
                {"closes_at": "Closing time must be later than opening time."}
            )
        return attrs


class WorkingHoursWriteSerializer(serializers.Serializer):
    """The whole week in one request.

    A provider setting hours wants to set the week, not to make seven requests.
    """

    days = WorkingHoursSerializer(many=True)

    def validate_days(self, days):
        weekdays = [day["weekday"] for day in days]
        duplicates = {day for day in weekdays if weekdays.count(day) > 1}
        if duplicates:
            names = ", ".join(WEEKDAY_LABELS[d] for d in sorted(duplicates))
            raise serializers.ValidationError(f"Repeated weekday: {names}.")

        out_of_range = [day for day in weekdays if not 0 <= day <= 6]
        if out_of_range:
            raise serializers.ValidationError("Weekday must be 0 (Monday) to 6 (Sunday).")
        return days


class AvailabilityToggleSerializer(serializers.Serializer):
    """Accepting bookings, or not.

    Separate from the shop serializer because turning this off is the single
    most consequential thing a provider can do from the app, and it deserves an
    explicit, self-describing call.
    """

    is_accepting_bookings = serializers.BooleanField()

    def validate_is_accepting_bookings(self, value: bool) -> bool:
        return value


class ShopSummarySerializer(serializers.ModelSerializer):
    """The smallest useful description of a shop, for a booking card."""

    class Meta:
        model = ProviderProfile
        fields = ["display_name", "service_type", "photo"]
