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
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.email import send_booking_confirmation
from api_keys.scopes import READ, WRITE, HasKeyScope, key_scoped
from bookings.consultation import questions_for as consultation_questions_for
from bookings.models import (
    Booking,
    BookingSeries,
    BookingStatus,
    WaitlistEntry,
    WaitlistOffer,
    has_room,
    is_within_working_hours,
)
from bookings.reschedule import late_window_message
from bookings.serializers import (
    BookingCreateSerializer,
    BookingSerializer,
    CancelBookingSerializer,
    QuoteRequestSerializer,
    RescheduleSerializer,
    WaitlistDeclineResultSerializer,
    WaitlistEntrySerializer,
    WaitlistJoinSerializer,
    WaitlistOfferSerializer,
)
from bookings.series import create_series, stop_series
from bookings.waitlist import (
    OfferUnavailable,
    accept_offer,
    cancel_entry,
    decline_offer,
    offer_freed_slot,
    slot_from_booking,
)
from core.exceptions import BusinessRuleViolation
from core.money import compute_deposit, format_minor
from core.notifications import format_appointment_time
from core.pagination import CompactPagination
from core.permissions import IsProvider
from core.schema import BAD_REQUEST, FORBIDDEN, NOT_FOUND, THROTTLED, UNAUTHORIZED
from payments.due import amount_due, default_kind
from payments.idempotency import idempotent
from payments.refunds import RefundError, refund_booking_deposit, refund_booking_payment
from promotions import loyalty
from promotions.models import PromoError, price, resolve
from providers.models import ProviderProfile, Service, Staff

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
@key_scoped(READ)
class BookingListView(APIView):
    """List bookings.

    ``?status=``, ``?upcoming=true`` and ``?past=true`` all work the same way for
    both roles.

    Reachable with an API key holding ``read``: a shop's till needs to see the
    day's appointments without anybody logging in as the owner.
    """

    permission_classes = [IsAuthenticated, HasKeyScope]
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
@key_scoped(WRITE)
class BookingCreateView(APIView):
    """Book an appointment.

    The request names the provider, the services and a start time. It does not
    name a price — the server looks the services up and decides.
    """

    permission_classes = [IsAuthenticated, HasKeyScope]
    throttle_scope = "booking"

    @extend_schema(operation_id="bookings_create")
    @idempotent("bookings.create")
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
@key_scoped(WRITE)
class BookingCancelView(APIView):
    """Cancel a booking.

    Only the customer or the provider it was booked with may cancel it. The old
    endpoint checked that the requester owned the appointment, but let nobody
    cancel a provider's side of it at all.
    """

    permission_classes = [IsAuthenticated, HasKeyScope]

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

        # A referral whose appointment fell over is not owed anything. Marked
        # lapsed rather than deleted, so the customer who was referred cannot
        # quietly be referred by somebody else after a cancellation.
        from promotions import referrals

        referrals.lapse_for_cancelled(booking)

        booking.refresh_from_db()
        notify_other_party(booking, cancelled_by=request.user)

        # An empty chair nobody knows about is a booking that did not happen.
        # Offer it to whoever was waiting, before it goes back to being public.
        offer_freed_slot(slot_from_booking(booking))

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

            # Points for the same reason, and on the same event: awarding them
            # at booking time means points for appointments that get cancelled,
            # refunded, or never happen.
            from promotions import loyalty

            loyalty.credit(booking)

            # A referral reward too, for the same reason. Paid out only here, so
            # it can only ever be triggered by an appointment that happened.
            from promotions import referrals

            referrals.reward(booking)

        return Response(BookingSerializer(booking, context={"request": request}).data)


class ConsultationFormsView(APIView):
    """The questions a customer is expected to answer for a selection of services.

    Public, because a shop's consultation form is part of what it offers: the
    customer can see what will be asked before they book, which is the only way
    the form can be consent rather than a surprise. Read-only, and it reveals
    nothing about any customer's answers.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="bookings_consultation_forms",
        summary="What to ask before booking",
        description=(
            "Every question attached to the selected services' forms, in order. "
            "Sent with the booking so the shop has what it needs to start."
        ),
        parameters=[
            OpenApiParameter(
                "services",
                str,
                description="Comma-separated service ids belonging to one provider.",
            ),
            OpenApiParameter("provider", int, description="Which shop those services belong to."),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        raw = request.query_params.get("services", "")
        ids = [part for part in str(raw).split(",") if part.strip()]
        if not ids:
            return Response({"forms": [], "questions": []})

        try:
            service_ids = [int(part) for part in ids]
        except ValueError:
            raise BusinessRuleViolation("Those were not service ids.") from None

        provider = get_object_or_404(ProviderProfile, pk=request.query_params.get("provider"))
        services = list(
            Service.objects.filter(
                pk__in=service_ids, provider=provider, is_active=True
            ).prefetch_related("consultation_forms__questions")
        )
        if not services:
            return Response({"forms": [], "questions": []})

        questions = consultation_questions_for(services)
        forms = {
            form.pk: form
            for service in services
            for form in service.consultation_forms.filter(is_active=True)
        }
        return Response(
            {
                "forms": [
                    {"id": form.pk, "name": form.name, "description": form.description}
                    for form in sorted(forms.values(), key=lambda f: f.name)
                ],
                "questions": [
                    {
                        "id": question.pk,
                        "form": question.form_id,
                        "label": question.label,
                        "help_text": question.help_text,
                        "kind": question.kind,
                        "choices": question.choices,
                        "is_required": question.is_required,
                    }
                    for question in questions
                ],
            }
        )


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
        return self._quote(request.query_params, request.user)

    @extend_schema(operation_id="bookings_quote_post")
    def post(self, request):
        return self._quote(request.data, request.user)

    def _quote(self, data, user=None):
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

        # The code is resolved here and priced here, from the same function the
        # checkout uses. A client that sends a discount of its own is ignored,
        # and a code that expires between quote and checkout is caught at both.
        try:
            promo = resolve(
                payload.get("promo_code"),
                provider=provider,
                service_ids={service.pk for service in services},
            )
        except PromoError as exc:
            raise BusinessRuleViolation(str(exc)) from exc

        points_off = loyalty.preview(
            user,
            provider,
            subtotal,
            int(payload.get("redeem_points") or 0),
        )
        breakdown = price(subtotal, code=promo, points_off=points_off)
        total = breakdown.total

        deposit_percent = max((service.deposit_percent for service in services), default=0)
        deposit, balance = compute_deposit(total, deposit_percent)
        late_cancel_fee, _ = compute_deposit(deposit, provider.late_cancel_fee_percent)

        return Response(
            {
                **breakdown.as_payload(),
                # Stated in words, because "the fee is 1% of what you pay"
                # is otherwise a puzzle on the screen.
                "promo_code": promo.code if promo else None,
                "promo_description": promo.description if promo else "",
                "points_spent": payload.get("redeem_points") or 0,
                "points_worth_minor": points_off,
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


def notify_other_party(booking: Booking, cancelled_by, *, rescheduled: bool = False) -> None:
    tokens = list(
        (
            booking.customer.push_tokens.filter(active=True)
            if cancelled_by == booking.provider.user
            else booking.provider.user.push_tokens.filter(active=True)
        ).values_list("token", flat=True)
    )
    if tokens:
        if rescheduled:
            send_push(
                tokens,
                title="Appointment moved",
                body=(f"{booking.reference} is now {format_appointment_time(booking)}"),
                data={"screen": "appointments"},
            )
        else:
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


class WaitlistView(APIView):
    """Join, see and leave the waitlist.

    A window rather than a single slot, because "any time this week" is what
    most people mean and pinning one minute would mean the waitlist misses
    almost every cancellation — the one thing it exists for.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="bookings_waitlist_join",
        summary="Join the waitlist",
        description=(
            "Tells us when a matching slot frees up. You get first refusal on "
            "it for a short window before it goes back to being public."
        ),
        request=WaitlistJoinSerializer,
        responses={201: WaitlistEntrySerializer},
    )
    def post(self, request):
        serializer = WaitlistJoinSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        entry = serializer.save()
        return Response(WaitlistEntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="bookings_waitlist_list",
        summary="Your waitlist entries",
        responses={200: WaitlistEntrySerializer(many=True)},
    )
    def get(self, request):
        entries = WaitlistEntry.objects.filter(customer=request.user).select_related(
            "provider", "service", "staff"
        )
        return Response(WaitlistEntrySerializer(entries, many=True).data)


class WaitlistEntryDetailView(APIView):
    """Leave the waitlist, releasing any slot held for you."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="bookings_waitlist_leave",
        summary="Leave the waitlist",
        description="Stops telling you about this slot, and frees any you were holding.",
        responses={204: None},
    )
    def delete(self, request, pk: int):
        entry = get_object_or_404(WaitlistEntry, pk=pk, customer=request.user)
        cancel_entry(entry)
        return Response(status=status.HTTP_204_NO_CONTENT)


class WaitlistOfferListView(APIView):
    """Slots currently being held for you."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="bookings_waitlist_offers",
        summary="Slots being held for you",
        description="Each one has a countdown. When it runs out it goes to the next person.",
        responses={200: WaitlistOfferSerializer(many=True)},
    )
    def get(self, request):
        offers = (
            WaitlistOffer.objects.filter(entry__customer=request.user, status="pending")
            .select_related("entry__provider", "entry__service", "staff")
            .order_by("expires_at")
        )
        return Response(WaitlistOfferSerializer(offers, many=True).data)


class _OfferView(APIView):
    """Shared lookup for the offer endpoints.

    An offer is found through the customer it belongs to, so asking about
    somebody else's is a 404 rather than a 403 — the response should not
    confirm that an offer exists at all.
    """

    permission_classes = [IsAuthenticated]

    def _offer(self, request, pk: int) -> WaitlistOffer:
        return get_object_or_404(
            WaitlistOffer.objects.select_related("entry", "entry__service"),
            pk=pk,
            entry__customer=request.user,
        )


class WaitlistOfferAcceptView(_OfferView):
    """Take a held slot."""

    @extend_schema(
        operation_id="bookings_waitlist_accept",
        summary="Take a held slot",
        description=(
            "Creates the booking. The full booking rules run again rather than "
            "trusting the offer, because an entry can sit for days across a "
            "price change or a revised cancellation policy."
        ),
        request=None,
        responses={201: BookingSerializer},
    )
    def post(self, request, pk: int):
        offer = self._offer(request, pk)
        try:
            booking = accept_offer(offer)
        except OfferUnavailable as exc:
            raise BusinessRuleViolation(str(exc)) from exc

        return Response(
            BookingSerializer(booking, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class WaitlistOfferDeclineView(_OfferView):
    """Give a held slot back to whoever is next."""

    @extend_schema(
        operation_id="bookings_waitlist_decline",
        summary="Give a held slot back",
        description="The slot goes to the next person. You stay on the waitlist.",
        request=None,
        responses={200: WaitlistDeclineResultSerializer},
    )
    def post(self, request, pk: int):
        offer = self._offer(request, pk)
        next_offer = decline_offer(offer)

        return Response(
            # Whether somebody else took it. Without this the customer who has
            # already declined is left wondering.
            {"declined": True, "passed_on": next_offer is not None},
            status=status.HTTP_200_OK,
        )


class BookingRescheduleView(APIView):
    """Move an appointment to a different time.

    Keeps the same booking: same reference, same payments, same reminders.
    Inside the cancellation window it does not move at all — it cancels, and
    says so, because a reschedule button that silently dodges the late-cancel
    fee is a way to never pay one.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="bookings_reschedule",
        summary="Move a booking to a new time",
        description=(
            "The reference, the payments and the reminders all follow the "
            "booking. Inside the cancellation window this cancels instead and "
            "returns `rescheduled: false`."
        ),
        request=RescheduleSerializer,
        responses={200: BookingSerializer},
    )
    def post(self, request, reference: str):
        from bookings.reschedule import (
            PriceChanged,
            RescheduleRefused,
            reschedule,
        )

        body = RescheduleSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        starts_at = body.validated_data["starts_at"]

        booking = lookup_booking(
            Booking.objects.filter(visible_bookings(request.user)).select_related(
                "provider__user", "customer", "provider", "staff"
            ),
            reference,
        )

        # The fee rule, applied before anything else so the answer is the same
        # one a cancellation would have given.
        if request.user == booking.customer and booking.is_late_cancellation():
            from bookings.policy import apply_cancellation
            from payments.refunds import RefundError, refund_booking_deposit

            late_cancel_fee = booking.late_cancel_fee
            apply_cancellation(booking, by_provider=False, reason="Moved to a new time")

            try:
                refund_booking_deposit(booking, forfeited=booking.late_cancel_fee > 0)
            except RefundError as exc:
                logger.warning("Could not settle a reschedule refund: %s", exc)

            booking.refresh_from_db()

            return Response(
                {
                    "rescheduled": False,
                    "cancelled": True,
                    "late_cancel_fee": late_cancel_fee,
                    "message": late_window_message(booking),
                    "booking": BookingSerializer(booking, context={"request": request}).data,
                },
                status=status.HTTP_200_OK,
            )

        try:
            reschedule(
                booking,
                starts_at,
                accept_price_change=body.validated_data["accept_price_change"],
            )
        except PriceChanged as changed:
            # A different number is not a failure to report — it is something
            # the customer has to agree to. Both figures go back so the app can
            # show the difference rather than making them remember.
            return Response(
                {
                    "rescheduled": False,
                    "reason": "price_changed",
                    "message": changed.message(),
                    "old_total": changed.old_total,
                    "new_total": changed.new_total,
                    "difference": changed.difference,
                },
                status=status.HTTP_409_CONFLICT,
            )
        except RescheduleRefused as refused:
            raise BusinessRuleViolation(refused.message) from refused

        notify_other_party(booking, cancelled_by=request.user, rescheduled=True)

        return Response(
            BookingSerializer(booking, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )


class BookingSeriesSerializer(serializers.ModelSerializer):
    """A series and where its next visit lands."""

    next_starts_at = serializers.SerializerMethodField()
    next_occurrence_index = serializers.SerializerMethodField()
    created_occurrences = serializers.IntegerField(read_only=True)
    service_names = serializers.SerializerMethodField()
    staff_name = serializers.SerializerMethodField()

    class Meta:
        model = BookingSeries
        fields = [
            "id",
            "provider",
            "staff",
            "staff_name",
            "starts_at",
            "interval_days",
            "total_occurrences",
            "created_occurrences",
            "status",
            "next_starts_at",
            "next_occurrence_index",
            "service_names",
        ]
        read_only_fields = fields

    def get_next_occurrence_index(self, obj: BookingSeries) -> int | None:
        return obj.next_index()

    def get_next_starts_at(self, obj: BookingSeries) -> str | None:
        index = obj.next_index()
        if index is None:
            return None
        return obj.occurs_at(index).isoformat()

    def get_service_names(self, obj: BookingSeries) -> list[str]:
        first = obj.bookings.order_by("occurrence_index").first()
        if first is None:
            return []
        return [item.name for item in first.items.all()]

    def get_staff_name(self, obj: BookingSeries) -> str | None:
        return obj.staff.name if obj.staff else None


class BookingSeriesCreateSerializer(serializers.Serializer):
    """Book several visits at once.

    Only ``services``, ``starts_at``, ``interval_days`` and ``total_occurrences``
    are taken from the client. The dates of the later visits are worked out from
    the first one on the server: a client that chose its own dates could put two
    occurrences in the same week.
    """

    provider = serializers.IntegerField()
    services = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    starts_at = serializers.DateTimeField()
    interval_days = serializers.IntegerField(min_value=1, max_value=365)
    total_occurrences = serializers.IntegerField(min_value=2, max_value=52)
    staff = serializers.IntegerField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")

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
            raise BusinessRuleViolation(
                "One or more of those services is not available from this provider."
            )

        starts_at = attrs["starts_at"]
        now = timezone.now()
        if starts_at <= now:
            raise BusinessRuleViolation("That time has already passed. Pick a later slot.")

        # A year is plenty for anything anybody means by a haircut schedule,
        # and it stops "six visits, every eight months" being accepted as a
        # series. The 90-day booking limit is *not* applied here: a trim every
        # four weeks for six months is the whole point of the feature, and the
        # visits beyond 90 days are simply materialised later, once they are
        # close enough to book.
        last = starts_at + timedelta(days=attrs["interval_days"] * (attrs["total_occurrences"] - 1))
        if last > now + timedelta(days=365):
            raise BusinessRuleViolation(
                "That series runs further ahead than we can keep. Try fewer "
                "visits, or a shorter interval."
            )

        staff = None
        if attrs.get("staff") is not None:
            staff = Staff.objects.filter(
                pk=attrs["staff"], provider=provider, is_active=True
            ).first()
            if staff is None:
                raise BusinessRuleViolation("That staff member is not available at this shop.")

        duration = timedelta(minutes=sum(service.duration_minutes for service in services))
        if not is_within_working_hours(provider, starts_at, starts_at + duration):
            raise BusinessRuleViolation(
                f"{provider.display_name} is open "
                f"{provider.opening_time:%H:%M} to {provider.closing_time:%H:%M}."
            )

        # Every visit has to land on a day the shop (and that barber) works.
        # A series that fails on week seven is worse than one refused up front.
        for index in range(attrs["total_occurrences"]):
            when = starts_at + timedelta(days=attrs["interval_days"] * index)
            if not is_within_working_hours(provider, when, when + duration):
                raise BusinessRuleViolation(
                    f"{when:%d %b %Y} is outside this shop's working hours."
                )
            if staff is not None and not staff.is_open_on(when.weekday()):
                raise BusinessRuleViolation(f"{staff.name} does not work on {when:%d %b}.")

        attrs["provider_obj"] = provider
        attrs["service_objs"] = services
        attrs["staff_obj"] = staff
        return attrs


class BookingSeriesView(APIView):
    """Start a run of visits, and see the ones already running."""

    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="bookings_series_list", summary="Your recurring bookings")
    def get(self, request):
        series = (
            BookingSeries.objects.filter(customer=request.user)
            .select_related("provider", "staff")
            .order_by("-created_at")
        )
        return Response(BookingSeriesSerializer(series, many=True).data)

    @extend_schema(
        operation_id="bookings_series_create",
        summary="Book a series of visits",
        description=(
            "Books the first visit now and records the rest. Each later visit "
            "becomes its own booking when it comes round, separately chargeable "
            "and separately cancellable."
        ),
        request=BookingSeriesCreateSerializer,
        responses={201: BookingSeriesSerializer},
    )
    def post(self, request):
        body = BookingSeriesCreateSerializer(data=request.data, context={"request": request})
        body.is_valid(raise_exception=True)

        services: list[Service] = body.validated_data["service_objs"]
        starts_at = body.validated_data["starts_at"]
        duration = timedelta(minutes=sum(service.duration_minutes for service in services))

        if not has_room(
            body.validated_data["provider_obj"],
            starts_at,
            starts_at + duration,
            staff=body.validated_data["staff_obj"],
        ):
            raise BusinessRuleViolation("That slot is already taken. Pick another time.")

        try:
            series, _first = create_series(
                customer=request.user,
                provider=body.validated_data["provider_obj"],
                services=services,
                starts_at=starts_at,
                interval_days=body.validated_data["interval_days"],
                total_occurrences=body.validated_data["total_occurrences"],
                staff=body.validated_data["staff_obj"],
                notes=body.validated_data.get("notes", ""),
            )
        except ValueError as exc:
            raise BusinessRuleViolation(str(exc)) from exc

        series = (
            BookingSeries.objects.filter(pk=series.pk).select_related("provider", "staff").get()
        )
        return Response(
            BookingSeriesSerializer(series, context={"request": request}).data, status=201
        )


class BookingSeriesStopView(APIView):
    """Call off the visits that have not been booked yet.

    The ones already on the calendar stay. Each of those is separately
    chargeable, so a customer who booked six weeks of trims is entitled to the
    two that have already happened to be paid for.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="bookings_series_stop",
        summary="Stop a recurring series",
        responses={200: BookingSeriesSerializer},
    )
    def post(self, request, pk: int):
        series = get_object_or_404(BookingSeries, pk=pk, customer=request.user)
        stop_series(series, request.user)
        series.refresh_from_db()
        return Response(BookingSeriesSerializer(series, context={"request": request}).data)
