"""Payment serializers."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from bookings.models import Booking, BookingStatus
from payments.choices import PaymentKind
from payments.models import Payment, PaymentStatus


@extend_schema_serializer(component_name="Payment")
class PaymentSerializer(serializers.ModelSerializer):
    """A payment, as read.

    ``amount`` is in the smallest currency unit; ``amount_display`` is for
    humans. Neither is client-settable.
    """

    amount_display = serializers.CharField(read_only=True)
    kind = serializers.CharField(read_only=True)
    booking_reference = serializers.CharField(source="booking.reference", read_only=True)
    is_captured = serializers.BooleanField(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "booking",
            "booking_reference",
            "kind",
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
        kind = self.context.get("kind")

        # A balance is paid on arrival, which means the booking is by then
        # confirmed. Refusing it here would make the balance unpayable online
        # the moment a deposit moved the booking forward — which is exactly
        # what a deposit does.
        payable_statuses = {BookingStatus.PENDING_PAYMENT}
        if kind == PaymentKind.BALANCE:
            payable_statuses |= {
                BookingStatus.CONFIRMED,
                BookingStatus.COMPLETED,
            }

        if booking.status not in payable_statuses:
            raise serializers.ValidationError(
                f"This booking is {booking.get_status_display().lower()} and no longer "
                f"needs paying."
            )
        # A booking can now be charged twice — deposit, then balance — so the
        # check is per-kind rather than "has this booking ever been paid".
        kind = self.context.get("kind")
        if kind and booking.payments.filter(kind=kind, status=PaymentStatus.CAPTURED).exists():
            label = "deposit" if kind == PaymentKind.DEPOSIT else "payment"
            raise serializers.ValidationError(
                f"The {label} for this booking has already been paid."
            )

        # DRF types `context` as a Mapping; it is a mutable dict at runtime.
        self.context["booking_obj"] = booking  # type: ignore[index]
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


class PaymentWebhookSerializer(serializers.Serializer):
    """Razorpay's webhook envelope.

    Documented here for the schema, but **not used to validate the request**.
    The signature covers the raw bytes, so it is verified first and in full —
    before this shape is parsed, and before any of it is trusted. Parsing an
    unverified payload and then checking a signature over the re-serialised
    version would be a different check, and a weaker one.
    """

    event = serializers.CharField(
        help_text="`payment.captured` or `payment.failed`; anything else is acknowledged and ignored."
    )
    payload = serializers.DictField()

    @staticmethod
    def payment_entity(body: dict) -> dict:
        """The payment entity out of a *verified* webhook body."""
        return (body.get("payload", {}).get("payment", {}) or {}).get("entity", {}) or {}
