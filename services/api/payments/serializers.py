"""Payment serializers."""

from __future__ import annotations

from rest_framework import serializers

from bookings.models import Booking, BookingStatus
from payments.models import Payment, PaymentStatus  # noqa: F401


class PaymentSerializer(serializers.ModelSerializer):
    """A payment, as read.

    ``amount`` is in the smallest currency unit; ``amount_display`` is for
    humans. Neither is client-settable.
    """

    amount_display = serializers.CharField(read_only=True)
    booking_reference = serializers.CharField(source="booking.reference", read_only=True)
    is_captured = serializers.BooleanField(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "booking",
            "booking_reference",
            "razorpay_order_id",
            "razorpay_payment_id",
            "amount",
            "amount_display",
            "currency",
            "status",
            "method",
            "is_captured",
            "captured_at",
            "failure_reason",
            "created_at",
        ]
        read_only_fields = fields


class CreateOrderSerializer(serializers.Serializer):
    """Ask Razorpay for an order to pay.

    Takes a booking reference and nothing else. The amount comes from the
    booking, which came from the server's own pricing.
    """

    booking = serializers.CharField(help_text="Booking reference, e.g. BK-7QK4M2.")

    def validate_booking(self, value: str) -> str:
        user = self.context["request"].user
        booking = Booking.objects.filter(customer=user, reference=value.upper()).first()
        if booking is None:
            # Same answer for "does not exist" and "not yours": a payment
            # endpoint is a fine place to enumerate other people's bookings.
            raise serializers.ValidationError("No such booking on your account.")
        if booking.status != BookingStatus.PENDING_PAYMENT:
            raise serializers.ValidationError(
                f"This booking is {booking.get_status_display().lower()} and no longer "
                f"needs paying."
            )
        if hasattr(booking, "payment") and booking.payment.is_captured:
            raise serializers.ValidationError("This booking has already been paid.")

        self.context["booking_obj"] = booking
        return value


class VerifyPaymentSerializer(serializers.Serializer):
    """Verify a checkout the customer just completed in the app.

    This **confirms** a payment, it does not create one. The signature is
    checked against Razorpay's secret, and then Razorpay itself is asked what
    happened. Nothing in this path lets a client assert that a payment
    succeeded — the old ``PUT /createorder`` did exactly that.
    """

    razorpay_order_id = serializers.CharField()
    razorpay_payment_id = serializers.CharField()
    razorpay_signature = serializers.CharField()


class WebhookSerializer(serializers.Serializer):
    """Razorpay's webhook envelope.

    The body is validated against ``RAZORPAY_WEBHOOK_SECRET`` before any of it
    is read — the signature covers the raw bytes, so it is checked first and in
    full, not after parsing.
    """

    event = serializers.CharField()
    payload = serializers.DictField()

    def validated_payment_entity(self) -> dict | None:
        entity = self.validated_data.get("payload", {}).get("payment", {}).get("entity", {})
        return entity or None
