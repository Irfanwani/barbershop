"""Booking endpoints.

A booking is the one place where the old API let the client dictate a number.
Everything here is priced on the server; see
[ADR 0003](../../../docs/decisions/0003-server-authoritative-pricing.md).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.email import send_booking_confirmation
from bookings.models import Booking, BookingStatus, has_room
from bookings.serializers import (
    BookingCreateSerializer,
    BookingSerializer,
    CancelBookingSerializer,
    QuoteRequestSerializer,
)
from core.exceptions import BusinessRuleViolation
from core.money import compute_deposit, compute_platform_fee, format_minor
from core.pagination import CompactPagination
from core.permissions import IsProvider
from core.schema import BAD_REQUEST, FORBIDDEN, NOT_FOUND, THROTTLED, UNAUTHORIZED
from payments.due import amount_due, default_kind
from payments.refunds import RefundError, refund_booking_deposit, refund_booking_payment
from providers.models import ProviderProfile, Service

logger = logging.getLogger(__name__)


def lookup_booking(queryset, reference: str) -> Booking:
    """Fetch one booking from ``queryset`` by numeric id or by reference code."""
    if reference.isdigit():
        return get_object_or_404(queryset, pk=int(reference))
    return get_object_or_404(queryset, reference=reference.upper())


def visible_bookings(user) -> Q:
    """Which bookings this user is allowed to see.

    Customers see their own; providers see the ones booked at their shop.
    Scoping in the queryset rather than filtering in Python means a provider
    with 10,000 bookings does not load all of them to show ten.
    """
    if user.is_provider and hasattr(user, "provider_profile"):
        return Q(provider__user=user)
    return Q(customer=user)


@extend_schema(
    tags=["bookings"],
    summary="List bookings",
    description=(
        "A customer sees their own; a provider sees the ones booked at their shop. "
        "`upcoming=true` and `past=true` are mutually exclusive."
    ),
    parameters=[
        OpenApiParameter("status", str, description="Comma-separated statuses."),
        OpenApiParameter("upcoming", bool),
        OpenApiParameter("past", bool),
        OpenApiParameter("page", int),
        OpenApiParameter("page_size", int),
    ],
    responses={
        200: OpenApiResponse(
            {
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "next": {"type": "string", "nullable": True},
                    "previous": {"type": "string", "nullable": True},
                    "results": {"type": "array", "items": {"$ref": "#/components/schemas/Booking"}},
                    "role": {"type": "string", "enum": ["customer", "provider"]},
                },
            },
            "A page of bookings",
        ),
        401: UNAUTHORIZED,
    },
)
class BookingListView(APIView):
    """List bookings.

    ``?status=``, ``?upcoming=true`` and ``?past=true`` all work the same way for
    both roles.
    """

    permission_classes = [IsAuthenticated]
    pagination_class = CompactPagination

    def get_queryset(self) -> list[Booking]:
        user = self.request.user
        queryset = (
            Booking.objects.filter(visible_bookings(user))
            .select_related("provider", "provider__user", "customer")
            .prefetch_related("items")
        )

        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status__in=status_filter.split(","))

        upcoming = self.request.query_params.get("upcoming")
        past = self.request.query_params.get("past")
        if upcoming in {"1", "true"}:
            queryset = queryset.filter(starts_at__gte=timezone.now())
        if past in {"1", "true"}:
            queryset = queryset.filter(starts_at__lt=timezone.now())

        return list(queryset.order_by("-starts_at"))

    @extend_schema(operation_id="bookings_list")
    def get(self, request):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(self.get_queryset(), request, view=self)
        serializer = BookingSerializer(page, many=True, context={"request": request})

        response = paginator.get_paginated_response(serializer.data)
        response.data["role"] = "provider" if request.user.is_provider else "customer"
        return response


@extend_schema(
    tags=["bookings"],
    summary="One booking",
    description="Addressable by numeric id or by the customer-facing reference.",
    responses={200: BookingSerializer, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
class BookingDetailView(APIView):
    """One booking, by id or by its customer-facing reference."""

    permission_classes = [IsAuthenticated]

    def get_object(self, request, reference: str) -> Booking:
        return lookup_booking(
            Booking.objects.filter(visible_bookings(request.user))
            .select_related("provider", "provider__user", "customer")
            .prefetch_related("items"),
            reference,
        )

    @extend_schema(operation_id="bookings_retrieve")
    def get(self, request, reference: str):
        booking = self.get_object(request, reference)
        return Response(BookingSerializer(booking, context={"request": request}).data)


@extend_schema(
    tags=["bookings"],
    summary="Book an appointment",
    description=(
        "Send the provider, the **service ids** and a start time. Do not send a price: "
        "the server looks the services up and decides what it costs. A total in the "
        "body is ignored, and the server's clock is used rather than the phone's."
    ),
    request=BookingCreateSerializer,
    responses={201: BookingSerializer, 400: BAD_REQUEST, 401: UNAUTHORIZED, 429: THROTTLED},
)
class BookingCreateView(APIView):
    """Book an appointment.

    The request names the provider, the services and a start time. It does not
    name a price — the server looks the services up and decides.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "booking"

    @extend_schema(operation_id="bookings_create")
    def post(self, request):
        if request.user.is_provider:
            raise BusinessRuleViolation(
                "Provider accounts book on behalf of a customer; sign in as one to book."
            )
        if not request.user.is_verified:
            raise BusinessRuleViolation("Please verify your email address before booking.")

        serializer = BookingCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()

        send_booking_confirmation(
            to=request.user.email,
            reference=booking.reference,
            provider_name=booking.provider.display_name,
            starts_at=booking.starts_at.isoformat(),
        )
        notify_provider(booking)

        return Response(
            BookingSerializer(booking, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["bookings"],
    summary="Cancel a booking",
    description="Either the customer or the provider it was booked with may cancel.",
    request=CancelBookingSerializer,
    responses={200: BookingSerializer, 400: BAD_REQUEST, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
class BookingCancelView(APIView):
    """Cancel a booking.

    Only the customer or the provider it was booked with may cancel it. The old
    endpoint checked that the requester owned the appointment, but let nobody
    cancel a provider's side of it at all.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="bookings_cancel",
        description=(
            "Either party may cancel. A customer cancelling inside the shop's "
            "cancellation window still succeeds, but forfeits the agreed slice of "
            "their deposit — the refusal case is a booking that cannot be cancelled "
            "at all. The window and the fee are the ones frozen on the booking."
        ),
    )
    def post(self, request, reference: str):
        from bookings.policy import apply_cancellation

        booking = lookup_booking(
            Booking.objects.filter(visible_bookings(request.user)).select_related(
                "provider__user", "customer"
            ),
            reference,
        )

        if not booking.can_be_cancelled:
            raise BusinessRuleViolation(
                f"A {booking.get_status_display().lower()} booking cannot be cancelled."
            )

        reason_serializer = CancelBookingSerializer(data=request.data)
        reason_serializer.is_valid(raise_exception=True)

        outcome = apply_cancellation(
            booking,
            by_provider=request.user != booking.customer,
            reason=reason_serializer.validated_data["reason"],
        )

        # Move the money now, not later. The cancellation succeeded either
        # way; a gateway that refuses to refund should not make it look like it
        # did not happen.
        try:
            refund_booking_deposit(booking, forfeited=outcome.deposit_forfeited)
            if not outcome.deposit_refundable:
                refund_booking_payment(booking, reason="Deposit forfeited, late cancellation")
        except RefundError as exc:
            logger.warning("Could not settle the refund for %s: %s", booking.reference, exc)
            outcome.message += " We could not start the refund automatically."

        booking.refresh_from_db()
        notify_other_party(booking, cancelled_by=request.user)

        # What happened to the money, in words. A customer who loses part of a
        # deposit deserves to be told here, not by noticing on their statement.
        payload = BookingSerializer(booking, context={"request": request}).data
        payload["cancellation"] = outcome.as_dict()
        return Response(payload)


class CollectBalanceSerializer(serializers.Serializer):
    """Take the balance in the shop.

    Amount is optional and defaults to everything outstanding, because that is
    what happens in practice: the customer settles up in full.
    """

    amount = serializers.IntegerField(
        required=False, min_value=1, help_text="Defaults to the full outstanding balance."
    )
    method = serializers.ChoiceField(choices=["cash", "upi", "card"], default="cash")
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)


class BookingCollectView(APIView):
    """Record what the customer paid at the counter.

    Provider-only, and deliberately not a booking *transition*: taking the money
    and marking the appointment finished are two different decisions, and a
    customer who paid and then walked out has still been paid.
    """

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(
        operation_id="bookings_collect",
        summary="Record a payment taken in the shop",
        request=CollectBalanceSerializer,
        responses={
            200: BookingSerializer,
            400: BAD_REQUEST,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    )
    def post(self, request, reference: str):
        from bookings.collect import NothingToCollect, collect_cash

        booking = lookup_booking(
            Booking.objects.filter(provider__user=request.user).select_related(
                "provider__user", "customer"
            ),
            reference,
        )

        serializer = CollectBalanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        amount = serializer.validated_data.get("amount") or amount_due(
            booking, default_kind(booking)
        )

        try:
            collect_cash(
                booking,
                amount,
                method=serializer.validated_data["method"],
                note=serializer.validated_data.get("note", ""),
            )
        except NothingToCollect as exc:
            raise BusinessRuleViolation(str(exc)) from exc

        booking.refresh_from_db()
        return Response(BookingSerializer(booking, context={"request": request}).data)


@extend_schema(
    tags=["bookings"],
    summary="Move a booking along",
    description=(
        "Provider-only. `action` is one of accept, decline, complete, no-show. Each is "
        "only valid from certain states and is refused otherwise."
    ),
    request=None,
    responses={200: BookingSerializer, 400: BAD_REQUEST, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
class BookingStatusView(APIView):
    """Advance a booking's lifecycle.

    Accept/confirm and complete are provider-only; cancel is on its own endpoint
    because both roles may do it.
    """

    permission_classes = [IsAuthenticated]

    ALLOWED = {
        "accept": (
            BookingStatus.AWAITING_CONFIRMATION,
            {BookingStatus.CONFIRMED},
        ),
        "decline": (
            BookingStatus.AWAITING_CONFIRMATION,
            {BookingStatus.CANCELLED_BY_PROVIDER},
        ),
        "complete": (
            BookingStatus.CONFIRMED,
            {BookingStatus.COMPLETED},
        ),
        "no-show": (
            BookingStatus.CONFIRMED,
            {BookingStatus.NO_SHOW},
        ),
    }

    @extend_schema(operation_id="bookings_transition")
    def post(self, request, reference: str, action: str):
        if action not in self.ALLOWED:
            raise NotFound(f"There is no such booking action: {action}.")

        booking = lookup_booking(
            Booking.objects.filter(provider__user=request.user).select_related(
                "provider__user", "customer"
            ),
            reference,
        )

        allowed_from, outcomes = self.ALLOWED[action]
        if booking.status not in allowed_from:
            raise BusinessRuleViolation(
                f"A {booking.get_status_display().lower()} booking cannot be {action}ed."
            )

        if action == "complete":
            booking.completed_at = timezone.now()

        booking.status = next(iter(outcomes))
        booking.save(update_fields=["status", "completed_at", "updated_at"])

        if action == "complete":
            # The appointment happened, so the shop has earned its share. Credited
            # on completion rather than on booking because a booking can still be
            # cancelled or turn into a no-show.
            from payments.ledger import credit_earning

            credit_earning(
                booking.provider,
                gross=booking.subtotal,
                booking_reference=booking.reference,
            )

        return Response(BookingSerializer(booking, context={"request": request}).data)


@extend_schema(
    tags=["bookings"],
    summary="What would this booking cost?",
    description=(
        "Call this before checkout so the customer agrees to the server's number. The "
        "quote and the booking use the same pricing code, so they cannot disagree."
    ),
    request=QuoteRequestSerializer,
    responses={
        200: OpenApiResponse(
            {
                "type": "object",
                "properties": {
                    "currency": {"type": "string", "example": "INR"},
                    "subtotal": {"type": "integer"},
                    "platform_fee": {"type": "integer"},
                    "total": {"type": "integer"},
                    "subtotal_display": {"type": "string", "example": "₹250.00"},
                    "platform_fee_display": {"type": "string", "example": "₹2.50"},
                    "total_display": {"type": "string", "example": "₹252.50"},
                    "duration_minutes": {"type": "integer"},
                    "starts_at": {"type": "string", "format": "date-time"},
                    "ends_at": {"type": "string", "format": "date-time"},
                    "items": {"type": "array", "items": {"type": "object"}},
                    "is_available": {"type": "boolean"},
                },
            },
            "The server's price for this booking",
        ),
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
        404: NOT_FOUND,
    },
)
class QuoteView(APIView):
    """What would this booking cost?

    The checkout screen calls this before it commits, so the customer sees the
    server's number rather than one the app made up.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="bookings_quote_get")
    def get(self, request):
        return self._quote(request.query_params)

    @extend_schema(operation_id="bookings_quote_post")
    def post(self, request):
        return self._quote(request.data)

    def _quote(self, data):
        serializer = QuoteRequestSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        provider = get_object_or_404(ProviderProfile, pk=payload["provider"])
        services = list(
            Service.objects.filter(pk__in=payload["services"], provider=provider, is_active=True)
        )
        if len(services) != len(payload["services"]):
            raise BusinessRuleViolation(
                "One or more of those services is not available from this provider."
            )

        starts_at = payload["starts_at"]
        duration = timedelta(minutes=sum(service.duration_minutes for service in services))
        ends_at = starts_at + duration

        subtotal = sum(service.price for service in services)
        platform_fee = compute_platform_fee(subtotal, settings.PLATFORM_FEE_PERCENT)
        total = subtotal + platform_fee

        deposit_percent = max((service.deposit_percent for service in services), default=0)
        deposit, balance = compute_deposit(total, deposit_percent)
        late_cancel_fee, _ = compute_deposit(deposit, provider.late_cancel_fee_percent)

        return Response(
            {
                "currency": "INR",
                "subtotal": subtotal,
                "subtotal_display": format_minor(subtotal),
                "platform_fee": platform_fee,
                "platform_fee_display": format_minor(platform_fee),
                "total": total,
                "total_display": format_minor(total),
                # Shown before checkout, never applied after. A deposit the
                # customer discovers at the payment screen is a complaint.
                "deposit_percent": deposit_percent,
                "deposit": deposit,
                "deposit_display": format_minor(deposit),
                "balance": balance,
                "balance_display": format_minor(balance),
                # The policy, quoted before checkout. A customer who only finds
                # out about a cancellation fee when they cancel it has been told
                # too late to consent to it.
                "cancellation_window_hours": provider.cancellation_window_hours,
                "late_cancel_fee_percent": provider.late_cancel_fee_percent,
                "late_cancel_fee": late_cancel_fee,
                "late_cancel_fee_display": format_minor(late_cancel_fee),
                "duration_minutes": int(duration.total_seconds() // 60),
                "starts_at": starts_at,
                "ends_at": ends_at,
                "items": [
                    {
                        "service_id": service.id,
                        "name": service.name,
                        "unit_price": service.price,
                        "unit_price_display": format_minor(service.price),
                        "duration_minutes": service.duration_minutes,
                    }
                    for service in services
                ],
                "is_available": has_room(provider, starts_at, ends_at),
            }
        )


def notify_provider(booking: Booking) -> None:
    """Best-effort push to the provider's devices.

    Notification is not part of the booking transaction. A push service being
    down must not roll back a booking the customer paid for.
    """
    tokens = list(
        booking.provider.user.push_tokens.filter(active=True).values_list("token", flat=True)
    )
    if not tokens:
        return
    send_push(
        tokens,
        title="New booking",
        body=f"{booking.customer.display_name} booked {booking.reference}",
        data={"screen": "appointments"},
    )


def notify_other_party(booking: Booking, cancelled_by) -> None:
    tokens = list(
        (
            booking.customer.push_tokens.filter(active=True)
            if cancelled_by == booking.provider.user
            else booking.provider.user.push_tokens.filter(active=True)
        ).values_list("token", flat=True)
    )
    if tokens:
        send_push(
            tokens,
            title="Booking cancelled",
            body=f"{booking.reference} was cancelled",
            data={"screen": "appointments"},
        )


def send_push(tokens: list[str], *, title: str, body: str, data: dict) -> None:
    """Fan a message out to a list of Expo push tokens.

    Swallows every failure on purpose — see :func:`notify_provider`.
    """
    import requests
    from django.conf import settings

    if not settings.PUSH_NOTIFICATION_URL:
        logger.debug("No PUSH_NOTIFICATION_URL configured; skipping push for %s", title)
        return

    try:
        requests.post(
            settings.PUSH_NOTIFICATION_URL,
            json={"to": tokens, "title": title, "body": body, "data": data},
            timeout=5,
        )
    except Exception:
        logger.exception("Could not deliver a push notification (%s)", title)
