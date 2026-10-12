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
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking, BookingStatus
from bookings.serializers import BookingSerializer
from core.exceptions import BusinessRuleViolation
from core.permissions import IsProvider
from core.schema import BAD_REQUEST, FORBIDDEN, NOT_FOUND, UNAUTHORIZED
from payments.due import amount_due, default_kind, requested_kind
from payments.idempotency import idempotent
from payments.models import Payment, PaymentStatus
from payments.refunds import reconcile
from payments.serializers import (
    CreateOrderSerializer,
    PaymentSerializer,
    PaymentWebhookSerializer,
    VerifyPaymentSerializer,
)
from payments.services import (
    create_order,
    credentials_configured,
    fetch_payment,
    verify_payment_signature,
    verify_webhook_signature,
)

#: Refunds are initiated synchronously but settle asynchronously, so these
#: have to be handled or a refund that succeeded looks like one still owed.
REFUND_EVENTS = {"refund.processed", "refund.failed"}

logger = logging.getLogger(__name__)


@extend_schema(
    tags=["payments"],
    summary="Start a payment",
    description=(
        "Creates a Razorpay order for the booking's total. The amount is the "
        "server-computed figure and cannot be supplied by the caller."
    ),
    request=CreateOrderSerializer,
    responses={
        201: OpenApiResponse(
            {
                "type": "object",
                "properties": {
                    "payment": {"$ref": "#/components/schemas/Payment"},
                    "razorpay": {
                        "type": "object",
                        "properties": {
                            "key_id": {"type": "string"},
                            "order_id": {"type": "string"},
                            "amount": {"type": "integer"},
                            "currency": {"type": "string"},
                        },
                    },
                    "amount_display": {"type": "string", "example": "₹252.50"},
                },
            },
            "An order to hand to the Razorpay checkout",
        ),
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
    },
)
class CreateOrderView(APIView):
    """Create a Razorpay order for one of the caller's bookings.

    The amount is the booking's server-computed total. It is not, and cannot be,
    supplied by the caller.
    """

    @extend_schema(
        operation_id="payments_create_order",
        parameters=[
            OpenApiParameter(
                "kind",
                str,
                description=(
                    "`deposit` or `balance`. Defaults to whatever is still owed "
                    "right now: the deposit on a booking that needs one, "
                    "otherwise the full total."
                ),
            )
        ],
    )
    def _booking_for(self, request) -> Booking:
        """Resolve and validate the booking the caller means to pay for."""
        kind = requested_kind(request)
        serializer = CreateOrderSerializer(
            data=request.data, context={"request": request, "kind": kind}
        )
        serializer.is_valid(raise_exception=True)
        return serializer.context["booking_obj"]

    def post(self, request):
        booking = self._booking_for(request)

        kind = requested_kind(request) or default_kind(booking)
        amount = amount_due(booking, kind)

        if amount <= 0:
            raise BusinessRuleViolation("There is nothing left to pay for this booking.")

        if not credentials_configured():
            raise BusinessRuleViolation(
                "Payments are not configured on this server yet. Please try cash at the shop."
            )

        try:
            order = create_order(
                amount=amount,
                currency=booking.currency,
                receipt=booking.reference,
                notes={"booking": booking.reference, "kind": kind},
            )
        except Exception as exc:
            logger.exception("Razorpay order creation failed for %s", booking.reference)
            raise BusinessRuleViolation(
                "We could not start the payment. Please try again in a moment."
            ) from exc

        payment = Payment.objects.create(
            booking=booking,
            kind=kind,
            razorpay_order_id=order["id"],
            amount=amount,
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
                "amount_display": format_minor_amount(amount, booking.currency),
                "amount_due_display": format_minor_amount(
                    booking.total - booking.amount_paid, booking.currency
                ),
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["payments"],
    summary="Confirm a checkout the customer just made",
    description=(
        "Verifies Razorpay's signature, then **asks Razorpay what actually happened** "
        "before recording anything. This confirms a payment; it never creates one. A "
        "client cannot mark its own booking paid by asserting success."
    ),
    request=VerifyPaymentSerializer,
    responses={200: PaymentSerializer, 400: BAD_REQUEST, 401: UNAUTHORIZED},
)
class VerifyPaymentView(APIView):
    """Confirm a checkout the customer just made.

    Verifies Razorpay's signature, then asks Razorpay what actually happened
    before recording anything. A client that claims success and is wrong gets a
    400, not a free haircut.
    """

    @extend_schema(
        operation_id="payments_verify",
        description=(
            "Send an `Idempotency-Key` header to make this safe to retry. A "
            "repeat returns the first response; the same key with a different "
            "body is refused."
        ),
    )
    @idempotent("payments.verify")
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


@extend_schema(
    tags=["payments"],
    summary="Razorpay's confirmation callback",
    description=(
        "Unauthenticated by necessity — Razorpay signs the request rather than "
        "carrying a token — so authenticity comes entirely from an HMAC over the raw "
        "body, checked before the body is parsed. Events that are not acted on are "
        "acknowledged rather than refused, because a non-2xx makes Razorpay retry "
        "forever."
    ),
    request=PaymentWebhookSerializer,
    responses={
        200: OpenApiResponse(
            {
                "type": "object",
                "properties": {
                    "handled": {"type": "boolean"},
                    "event": {"type": "string"},
                },
            },
            "Acknowledged",
        ),
        400: OpenApiResponse({"type": "object"}, "Bad or missing signature"),
    },
)
class PaymentWebhookView(APIView):
    """Razorpay's confirmation callback.

    Unauthenticated by necessity — Razorpay signs the request rather than
    carrying a token — so authenticity comes entirely from the HMAC over the raw
    body. If that does not check out, the request is refused without being
    parsed.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def _refund_event(self, event: str, payload: dict):
        """Settle a refund the gateway has finished with.

        A refund is initiated synchronously, but "initiated" is not "done": the
        gateway can take days to process one, and it can fail one outright.
        Without handling these, a refund that succeeded leaves the booking
        looking like money still owed, and a refund that failed looks like it
        succeeded.
        """
        entity = (payload.get("refund", {}) or {}).get("entity", {}) or {}
        refund_id = str(entity.get("id", ""))
        payment = (
            Payment.objects.filter(refund_id=refund_id).select_related("booking").first()
            if refund_id
            else None
        )

        if payment is None:
            # We record `refund_id` when we ask for the refund, so an unknown
            # one is either not ours or was initiated before this existed.
            # Not retried: it will never become known.
            logger.warning("Refund webhook for an unknown refund: %s", refund_id)
            return Response({"handled": False, "event": event})

        reconcile(payment, {**entity, "refund_id": refund_id})
        logger.info("Settled refund %s as %s", refund_id, entity.get("status", "unknown"))
        return Response({"handled": True, "event": event})

    @extend_schema(operation_id="payments_webhook")
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
        payload = body.get("payload", {}) or {}

        if event in REFUND_EVENTS:
            return self._refund_event(event, payload)

        entity = (payload.get("payment", {}) or {}).get("entity", {}) or {}

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


class RefundBookingSerializer(serializers.Serializer):
    """Refund what the customer paid towards a booking."""

    amount = serializers.IntegerField(
        required=False, min_value=1, help_text="Defaults to everything paid."
    )
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)


class RefundBookingView(APIView):
    """Give a customer's money back.

    Provider-only. The shop holds the money, so it is the shop that returns it —
    the platform never keeps a booking's balance, and this endpoint refuses to
    pretend otherwise.
    """

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(
        operation_id="payments_refund_booking",
        summary="Refund a booking",
        request=RefundBookingSerializer,
        responses={
            200: BookingSerializer,
            400: BAD_REQUEST,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    )
    def post(self, request, reference: str):
        from bookings.models import Booking as BookingModel
        from payments.refunds import RefundError, refund_booking_payment

        booking = get_object_or_404(
            BookingModel.objects.filter(provider__user=request.user).select_related(
                "provider__user", "customer"
            ),
            reference=reference.upper(),
        )

        serializer = RefundBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            refund_booking_payment(
                booking,
                amount=serializer.validated_data.get("amount"),
                reason=serializer.validated_data.get("reason", ""),
            )
        except RefundError as exc:
            raise BusinessRuleViolation(str(exc)) from exc

        booking.refresh_from_db()
        return Response(BookingSerializer(booking, context={"request": request}).data)


@extend_schema(
    tags=["payments"],
    summary="One payment, by Razorpay order id",
    request=None,
    responses={200: PaymentSerializer, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
class PaymentDetailView(APIView):
    """Read one payment, by its Razorpay order id."""

    @extend_schema(operation_id="payments_retrieve")
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
