"""Payment endpoints.

The rule this module exists to enforce: **a client can never mark its own
booking paid.** The old API accepted ``PUT /api/payments/createorder`` with an
appointment id in the body and set ``paid=True`` on it, having checked only that
*someone* was authenticated. Any user could mark any booking paid.

Here, payment state advances only when:

1. Razorpay's webhook arrives with a valid HMAC signature over the raw body, or
2. the server asks Razorpay directly what happened to a payment id.
"""

from __future__ import annotations

import json
import logging

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking, BookingStatus
from core.exceptions import BusinessRuleViolation
from payments.models import Payment, PaymentStatus
from payments.serializers import (
    CreateOrderSerializer,
    PaymentSerializer,
    VerifyPaymentSerializer,
)
from payments.services import (
    create_order,
    credentials_configured,
    fetch_payment,
    verify_payment_signature,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)


class CreateOrderView(APIView):
    """Create a Razorpay order for one of the caller's bookings.

    The amount is the booking's server-computed total. It is not, and cannot be,
    supplied by the caller.
    """

    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        booking: Booking = serializer.context["booking_obj"]

        if not credentials_configured():
            raise BusinessRuleViolation(
                "Payments are not configured on this server yet. Please try cash at the shop."
            )

        try:
            order = create_order(
                amount=booking.total,
                currency=booking.currency,
                receipt=booking.reference,
                notes={"booking": booking.reference},
            )
        except Exception as exc:
            logger.exception("Razorpay order creation failed for %s", booking.reference)
            raise BusinessRuleViolation(
                "We could not start the payment. Please try again in a moment."
            ) from exc

        payment = Payment.objects.create(
            booking=booking,
            razorpay_order_id=order["id"],
            amount=booking.total,
            currency=booking.currency,
            status=PaymentStatus.CREATED,
        )

        return Response(
            {
                "payment": PaymentSerializer(payment).data,
                "razorpay": {
                    "key_id": order["key_id"],
                    "order_id": order["id"],
                    "amount": order["amount"],
                    "currency": order["currency"],
                },
                "amount_display": format_minor_amount(booking.total, booking.currency),
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyPaymentView(APIView):
    """Confirm a checkout the customer just made.

    Verifies Razorpay's signature, then asks Razorpay what actually happened
    before recording anything. A client that claims success and is wrong gets a
    400, not a free haircut.
    """

    def post(self, request):
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not verify_payment_signature(
            data["razorpay_order_id"], data["razorpay_payment_id"], data["razorpay_signature"]
        ):
            raise BusinessRuleViolation("We could not verify that payment. Please try again.")

        payment = Payment.objects.filter(
            razorpay_order_id=data["razorpay_order_id"],
            booking__customer=request.user,
        ).first()
        if payment is None:
            raise BusinessRuleViolation("No such payment on your account.")

        try:
            remote = fetch_payment(data["razorpay_payment_id"])
        except Exception as exc:
            logger.exception(
                "Could not fetch payment %s from Razorpay", data["razorpay_payment_id"]
            )
            raise BusinessRuleViolation(
                "We could not confirm the payment with our payment provider."
            ) from exc

        if remote.get("status") != "captured":
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = remote.get("status", "unknown")
            payment.save(update_fields=["status", "failure_reason", "updated_at"])
            return Response(PaymentSerializer(payment).data, status=status.HTTP_400_BAD_REQUEST)

        capture(payment, data["razorpay_payment_id"], data["razorpay_signature"])
        return Response(PaymentSerializer(payment).data)


class PaymentWebhookView(APIView):
    """Razorpay's confirmation callback.

    Unauthenticated by necessity — Razorpay signs the request rather than
    carrying a token — so authenticity comes entirely from the HMAC over the raw
    body. If that does not check out, the request is refused without being
    parsed.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        signature = request.headers.get("X-Razorpay-Signature", "")

        if not verify_webhook_signature(request.body, signature):
            logger.warning("Rejected a payment webhook with a bad signature")
            return Response(status=status.HTTP_400_BAD_REQUEST)

        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        event = body.get("event", "")
        entity = (body.get("payload", {}).get("payment", {}) or {}).get("entity", {}) or {}

        if event not in {"payment.captured", "payment.failed"}:
            # Acknowledge everything else. Returning non-2xx makes Razorpay retry
            # an event we will never act on.
            return Response({"handled": False, "event": event})

        order_id = entity.get("order_id", "")
        payment = (
            Payment.objects.filter(razorpay_order_id=order_id).select_related("booking").first()
        )

        if payment is None:
            # We do not retry either: an unknown order will never become known.
            logger.warning("Webhook for an unknown order: %s", order_id)
            return Response({"handled": False})

        if event == "payment.captured":
            capture(payment, entity.get("id", ""), "")
        else:
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = entity.get("error_description", "")[:255]
            payment.save(update_fields=["status", "failure_reason", "updated_at"])

        return Response({"handled": True})


class PaymentDetailView(APIView):
    """Read one payment, by its Razorpay order id."""

    def get(self, request, order_id: str):
        payment = get_object_or_404(
            Payment.objects.select_related("booking")
            .filter(razorpay_order_id=order_id)
            .filter(visible_payments(request.user))
        )
        return Response(PaymentSerializer(payment).data)


def visible_payments(user) -> Q:
    """Payments on the caller's own bookings, or at their own shop."""
    if user.is_provider and hasattr(user, "provider_profile"):
        return Q(booking__provider__user=user)
    return Q(booking__customer=user)


@transaction.atomic
def capture(payment: Payment, payment_id: str, signature: str) -> Payment:
    """Mark a payment captured and confirm the booking.

    Idempotent: Razorpay retries webhooks, and a second capture must not
    double-count anything. The booking status only moves forward.
    """
    if payment.status == PaymentStatus.CAPTURED:
        return payment

    payment.status = PaymentStatus.CAPTURED
    payment.razorpay_payment_id = payment_id or payment.razorpay_payment_id
    payment.razorpay_signature = signature or payment.razorpay_signature
    payment.captured_at = timezone.now()
    payment.save(
        update_fields=[
            "status",
            "razorpay_payment_id",
            "razorpay_signature",
            "captured_at",
            "updated_at",
        ]
    )

    booking = payment.booking
    if booking.status == BookingStatus.PENDING_PAYMENT:
        booking.status = (
            BookingStatus.AWAITING_CONFIRMATION
            if booking.provider.requires_approval
            else BookingStatus.CONFIRMED
        )
        booking.save(update_fields=["status", "updated_at"])

    return payment


def format_minor_amount(amount: int, currency: str) -> str:
    from core.money import format_minor

    return format_minor(amount, currency)
