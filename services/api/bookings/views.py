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
from rest_framework import status
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
from core.money import compute_platform_fee, format_minor
from core.pagination import CompactPagination
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

    def get(self, request):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(self.get_queryset(), request, view=self)
        serializer = BookingSerializer(page, many=True, context={"request": request})

        response = paginator.get_paginated_response(serializer.data)
        response.data["role"] = "provider" if request.user.is_provider else "customer"
        return response


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

    def get(self, request, reference: str):
        booking = self.get_object(request, reference)
        return Response(BookingSerializer(booking, context={"request": request}).data)


class BookingCreateView(APIView):
    """Book an appointment.

    The request names the provider, the services and a start time. It does not
    name a price — the server looks the services up and decides.
    """

    permission_classes = [IsAuthenticated]
    throttle_scope = "booking"

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


class BookingCancelView(APIView):
    """Cancel a booking.

    Only the customer or the provider it was booked with may cancel it. The old
    endpoint checked that the requester owned the appointment, but let nobody
    cancel a provider's side of it at all.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, reference: str):
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

        is_customer = booking.customer == request.user
        booking.status = (
            BookingStatus.CANCELLED_BY_CUSTOMER
            if is_customer
            else BookingStatus.CANCELLED_BY_PROVIDER
        )
        booking.cancelled_at = timezone.now()
        booking.cancellation_reason = reason_serializer.validated_data["reason"]
        booking.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])

        notify_other_party(booking, cancelled_by=request.user)

        return Response(BookingSerializer(booking, context={"request": request}).data)


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

        return Response(BookingSerializer(booking, context={"request": request}).data)


class QuoteView(APIView):
    """What would this booking cost?

    The checkout screen calls this before it commits, so the customer sees the
    server's number rather than one the app made up.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return self._quote(request.query_params)

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

        return Response(
            {
                "currency": "INR",
                "subtotal": subtotal,
                "subtotal_display": format_minor(subtotal),
                "platform_fee": platform_fee,
                "platform_fee_display": format_minor(platform_fee),
                "total": total,
                "total_display": format_minor(total),
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
