"""Review serializers."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from core.exceptions import BusinessRuleViolation
from providers.models import ProviderProfile
from reviews.models import MAX_RATING, MIN_RATING, Review


class ReviewSerializer(serializers.ModelSerializer):
    """A review as it is read."""

    customer_display_name = serializers.CharField(source="customer.display_name", read_only=True)
    customer_username = serializers.CharField(source="customer.username", read_only=True)
    provider_name = serializers.CharField(source="provider.display_name", read_only=True)

    class Meta:
        model = Review
        fields = [
            "id",
            "provider",
            "provider_name",
            "customer_display_name",
            "customer_username",
            "booking",
            "rating",
            "comment",
            "provider_reply",
            "replied_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "provider_name",
            "customer_display_name",
            "customer_username",
            "provider_reply",
            "replied_at",
            "created_at",
        ]


class ReviewCreateSerializer(serializers.Serializer):
    """Leave a review.

    A review must be about a booking this customer actually made with this
    provider. The old endpoint accepted any rating, from anyone, about anyone —
    including 9 stars, because ``ratings`` had no range constraint.
    """

    provider = serializers.IntegerField()
    rating = serializers.IntegerField(min_value=MIN_RATING, max_value=MAX_RATING)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")
    booking = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, attrs: dict) -> dict:
        from bookings.models import Booking, BookingStatus

        user = self.context["request"].user
        provider = ProviderProfile.objects.filter(pk=attrs["provider"]).first()
        if provider is None:
            raise BusinessRuleViolation("That provider does not exist.")

        booking = None
        if attrs.get("booking"):
            booking = Booking.objects.filter(pk=attrs["booking"]).first()
            if booking is None:
                raise BusinessRuleViolation("That booking does not exist.")
            if booking.customer_id != user.pk:
                raise BusinessRuleViolation("That booking is not yours.")
            if booking.provider_id != provider.pk:
                raise BusinessRuleViolation("That booking was not with this provider.")
            if booking.status not in {
                BookingStatus.COMPLETED,
                BookingStatus.NO_SHOW,
                BookingStatus.CANCELLED_BY_CUSTOMER,
            }:
                raise BusinessRuleViolation("You can review once the appointment is over.")
            if hasattr(booking, "review"):
                raise BusinessRuleViolation("You have already reviewed this visit.")

        attrs["provider_obj"] = provider
        attrs["booking_obj"] = booking
        return attrs

    @transaction.atomic
    def create(self, validated_data: dict) -> Review:
        provider: ProviderProfile = validated_data["provider_obj"]
        review = Review.objects.create(
            customer=self.context["request"].user,
            provider=provider,
            booking=validated_data["booking_obj"],
            rating=validated_data["rating"],
            comment=validated_data.get("comment", ""),
        )
        # The provider's cached rating is denormalised onto their row so search
        # results do not run an aggregate per shop.
        provider.refresh_rating()
        return review


class ReviewReplySerializer(serializers.Serializer):
    """A provider's public reply."""

    provider_reply = serializers.CharField(max_length=1000, allow_blank=True)

    def save(self, **kwargs) -> Review:
        review: Review = self.instance
        review.provider_reply = self.validated_data["provider_reply"]
        review.replied_at = timezone.now()
        review.save(update_fields=["provider_reply", "replied_at", "updated_at"])
        return review


class ReviewCreateModelSerializer(serializers.ModelSerializer):
    """Model-bound variant, for the admin and any internal caller."""

    class Meta:
        model = Review
        fields = ["provider", "customer", "booking", "rating", "comment", "is_hidden"]

    def validate_rating(self, value: int) -> int:
        if not MIN_RATING <= value <= MAX_RATING:
            raise serializers.ValidationError(
                f"A rating has to be between {MIN_RATING} and {MAX_RATING}."
            )
        return value
