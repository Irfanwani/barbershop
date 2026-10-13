"""Booking serializers.

The important one here is :class:`BookingCreateSerializer`. It accepts service
ids and computes the price; it never accepts a total. See
[ADR 0003](../../../docs/decisions/0003-server-authoritative-pricing.md).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from bookings.consultation import (
    AnswersRejected,
    questions_for as consultation_questions_for,
    record_answers,
    validate_answers,
)
from bookings.models import (
    Booking,
    BookingItem,
    WaitlistEntry,
    WaitlistOffer,
    WaitlistStatus,
    has_room,
    is_within_working_hours,
)
from bookings.pricing import booking_items, price_appointment
from core.exceptions import BusinessRuleViolation
from core.money import format_minor
from promotions import loyalty
from promotions.models import PromoCode, PromoError, PromoRedemption, resolve
from providers.models import ProviderProfile, Service, Staff
from providers.serializers import ProviderSummarySerializer


class BookingItemSerializer(serializers.ModelSerializer):
    """One line of a booking.

    Reads the snapshot, not the live service row: if the provider raises this
    price next month, yesterday's invoice must not change.
    """

    line_total = serializers.IntegerField(read_only=True)
    unit_price_display = serializers.SerializerMethodField()

    class Meta:
        model = BookingItem
        fields = [
            "id",
            "service",
            "name",
            "unit_price",
            "unit_price_display",
            "quantity",
            "duration_minutes",
            "line_total",
        ]
        read_only_fields = fields

    def get_unit_price_display(self, obj: BookingItem) -> str:
        return format_minor(obj.unit_price)


class StaffSummarySerializer(serializers.ModelSerializer):
    """Who is doing the job, on a booking.

    Frozen with the rest of the booking. If the person later leaves the shop
    their name stays on the appointment they worked.
    """

    class Meta:
        model = Staff
        fields = ["id", "name", "photo"]


@extend_schema_serializer(component_name="Booking")
class BookingSerializer(serializers.ModelSerializer):
    items = BookingItemSerializer(many=True, read_only=True)
    provider = ProviderSummarySerializer(read_only=True)
    staff = StaffSummarySerializer(read_only=True)
    customer = serializers.SerializerMethodField()
    total_display = serializers.CharField(read_only=True)
    subtotal_display = serializers.SerializerMethodField()
    platform_fee_display = serializers.SerializerMethodField()
    duration_minutes = serializers.IntegerField(read_only=True)
    can_be_cancelled = serializers.BooleanField(read_only=True)
    is_paid = serializers.BooleanField(read_only=True)
    amount_paid = serializers.IntegerField(read_only=True)
    amount_due = serializers.IntegerField(read_only=True)
    requires_deposit = serializers.BooleanField(read_only=True)
    cancellation_deadline = serializers.DateTimeField(read_only=True)
    is_late_cancellation = serializers.SerializerMethodField()
    late_cancel_fee = serializers.IntegerField(read_only=True)
    late_cancel_fee_display = serializers.SerializerMethodField()
    deposit_display = serializers.SerializerMethodField()
    balance_display = serializers.SerializerMethodField()
    consultation_answers = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "reference",
            "provider",
            "staff",
            "customer",
            "consultation_answers",
            "status",
            "starts_at",
            "ends_at",
            "duration_minutes",
            "subtotal",
            "subtotal_display",
            "platform_fee",
            "platform_fee_display",
            "total",
            "total_display",
            "currency",
            "deposit",
            "deposit_display",
            "balance",
            "balance_display",
            "amount_paid",
            "amount_due",
            "requires_deposit",
            "cancellation_window_hours",
            "cancellation_deadline",
            "is_late_cancellation",
            "late_cancel_fee",
            "late_cancel_fee_display",
            "notes",
            "items",
            "can_be_cancelled",
            "is_paid",
            "cancelled_at",
            "cancellation_reason",
            "created_at",
        ]
        read_only_fields = fields

    def get_is_late_cancellation(self, obj: Booking) -> bool:
        """Whether cancelling *now* would cost the customer the fee.

        From the customer's side. The provider's view is different and is not
        this field.
        """
        return obj.is_late_cancellation()

    def get_late_cancel_fee_display(self, obj: Booking) -> str:
        return format_minor(obj.late_cancel_fee, obj.currency)

    def get_deposit_display(self, obj: Booking) -> str:
        return format_minor(obj.deposit, obj.currency)

    def get_balance_display(self, obj: Booking) -> str:
        return format_minor(obj.balance, obj.currency)

    def get_customer(self, obj: Booking) -> dict:
        user = obj.customer
        return {"id": user.id, "username": user.username, "display_name": user.display_name}

    def get_subtotal_display(self, obj: Booking) -> str:
        return format_minor(obj.subtotal, obj.currency)

    def get_platform_fee_display(self, obj: Booking) -> str:
        return format_minor(obj.platform_fee, obj.currency)

    def get_consultation_answers(self, obj: Booking) -> list:
        """The answers, with the sensitive ones withheld from everybody but
        the barber who has to act on them.

        Returned to the provider who owns *this* booking and to nobody else -
        not the customer, not another shop, not a staff member elsewhere. The
        check is against the booking's own provider, so a provider who later
        takes a booking at a shop they once worked for still cannot read an
        answer they were not given.

        Withheld rather than replaced with a placeholder: a row that says
        "hidden" still confirms how many questions there were and which ones
        were sensitive, which is itself the information the flag exists to
        protect.
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return []
        if not obj.provider.user_id == user.id:
            return []

        answers = obj.consultation_answers.all()
        if not getattr(user, "is_provider", False):
            # Staff see their own shop's bookings, so the same rule holds.
            return []
        return [
            {
                "id": answer.pk,
                "question": answer.question_id,
                "label": answer.label,
                "value": answer.value,
                "is_sensitive": answer.is_sensitive,
            }
            for answer in answers
        ]


class BookingListSerializer(BookingSerializer):
    """A booking as it appears in a list — same shape, fewer queries."""

    class Meta(BookingSerializer.Meta):
        pass


class QuoteRequestSerializer(serializers.Serializer):
    """Ask what a booking would cost, before committing to it."""

    provider = serializers.IntegerField()
    services = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    starts_at = serializers.DateTimeField()
    #: Optional. Priced server-side; the client never sends an amount.
    promo_code = serializers.CharField(required=False, allow_blank=True, max_length=32)
    #: Optional. How many points to spend. The server decides what that is
    #: worth and caps it.
    redeem_points = serializers.IntegerField(required=False, min_value=0, default=0)

    def validate_services(self, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise serializers.ValidationError("The same service was listed twice.")
        return value


class QuoteSerializer(serializers.Serializer):
    """The server's price for a booking.

    The client shows this and asks the customer to agree. A client that sends a
    different number in the booking request is ignored.
    """

    currency = serializers.CharField()
    subtotal = serializers.IntegerField()
    platform_fee = serializers.IntegerField()
    total = serializers.IntegerField()
    duration_minutes = serializers.IntegerField()
    subtotal_display = serializers.CharField()
    platform_fee_display = serializers.CharField()
    total_display = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    items = serializers.ListField(child=serializers.DictField())


class BookingCreateSerializer(serializers.Serializer):
    """Create a booking.

    Accepts ``provider``, ``services`` (ids) and ``starts_at``. The total is
    computed here from :class:`~providers.models.Service` rows, never read from
    the request.

    The old endpoint stored ``request.data['totalcost']`` verbatim, so a client
    could book a 900-rupee haircut for one rupee.
    """

    provider = serializers.IntegerField()
    #: Optional. A shop that has not named its staff takes bookings with this
    #: null, which is the same as it always was.
    staff = serializers.IntegerField(required=False, allow_null=True)
    services = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    starts_at = serializers.DateTimeField()
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    promo_code = serializers.CharField(required=False, allow_blank=True, max_length=32)
    #: Optional. How many points to spend. The server decides what that is
    #: worth and caps it, so a client cannot ask for a discount by sending a
    #: larger number here.
    redeem_points = serializers.IntegerField(required=False, min_value=0, default=0)
    #: Answers to whatever consultation forms the selected services carry. Each
    #: entry is ``{"question": <id>, "value": "..."}``. Validated against the
    #: forms themselves, so a client cannot ask the shop arbitrary questions.
    answers = serializers.ListField(child=serializers.DictField(), required=False, default=list)

    MAX_SERVICES = 10

    def validate_services(self, value: list[int]) -> list[int]:
        if len(value) > self.MAX_SERVICES:
            raise serializers.ValidationError(
                f"You can book at most {self.MAX_SERVICES} services in one visit."
            )
        if len(value) != len(set(value)):
            raise serializers.ValidationError("The same service was listed twice.")
        return value

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
            # Either an id does not exist, or it belongs to a different provider,
            # or it is retired. All three are the same answer to the client.
            raise BusinessRuleViolation(
                "One or more of those services is not available from this provider."
            )

        starts_at = attrs["starts_at"]
        duration = timedelta(minutes=sum(service.duration_minutes for service in services))
        ends_at = starts_at + duration

        now = timezone.now()

        # The server's clock, not the client's. The old check used a
        # `currentdatetime` string posted by the phone, so setting the clock
        # forward let you book yesterday.
        if starts_at <= now:
            raise BusinessRuleViolation("That time has already passed. Pick a later slot.")
        if starts_at > now + timedelta(days=90):
            raise BusinessRuleViolation("Bookings can only be made up to 90 days ahead.")

        if not is_within_working_hours(provider, starts_at, ends_at):
            raise BusinessRuleViolation(
                f"{provider.display_name} is open "
                f"{provider.opening_time:%H:%M} to {provider.closing_time:%H:%M}."
            )

        # Capacity, not bare overlap: a shop with four barbers can run four
        # simultaneous bookings.
        staff = None
        if attrs.get("staff") is not None:
            # Scoped to this provider on purpose. "That staff member does not
            # exist" and "that staff member is not ours" have to be the same
            # answer, or the endpoint confirms which shops someone works for.
            staff = Staff.objects.filter(
                pk=attrs["staff"], provider=provider, is_active=True
            ).first()
            if staff is None:
                raise BusinessRuleViolation("That staff member is not available at this shop.")

            if not staff.is_open_on(starts_at.weekday()):
                raise BusinessRuleViolation(f"{staff.name} does not work that day.")

            bounds = staff.day_bounds(starts_at.weekday())
            if bounds is None:
                raise BusinessRuleViolation(f"{staff.name} is not working that day.")
            opens_at, closes_at = bounds
            local = provider.localtime(starts_at)
            if not (opens_at <= local.time() and local.time() < closes_at):
                raise BusinessRuleViolation(
                    f"{staff.name} works {opens_at:%H:%M} to {closes_at:%H:%M} on that day."
                )

        if not has_room(provider, starts_at, ends_at, staff=staff):
            raise BusinessRuleViolation("That slot is already taken. Pick another time.")

        # Validated here rather than saved here, so a booking that cannot
        # happen is refused before any row exists.
        questions = consultation_questions_for(services)
        try:
            given = validate_answers(attrs.get("answers") or [], questions)
        except AnswersRejected as rejected:
            raise serializers.ValidationError(
                {"answers": rejected.details.get("answers", {})}
            ) from rejected

        attrs["provider_obj"] = provider
        attrs["staff_obj"] = staff
        attrs["service_objs"] = services
        attrs["ends_at"] = ends_at
        attrs["consultation_questions"] = questions
        attrs["consultation_answers"] = given
        return attrs

    def save(self, **kwargs) -> Booking:
        provider: ProviderProfile = self.validated_data["provider_obj"]
        services: list[Service] = self.validated_data["service_objs"]
        starts_at = self.validated_data["starts_at"]
        ends_at = self.validated_data["ends_at"]

        subtotal = sum(service.price for service in services)

        # Same resolution, same pricing function as the quote. A code that
        # expired in between is refused here rather than quietly ignored.
        try:
            promo = resolve(
                self.validated_data.get("promo_code"),
                provider=provider,
                service_ids={service.pk for service in services},
            )
        except PromoError as exc:
            raise BusinessRuleViolation(str(exc)) from exc

        points_off = loyalty.preview(
            self.context["request"].user,
            provider,
            subtotal,
            self.validated_data.get("redeem_points", 0),
        )
        # One implementation of the money, shared with the recurring series so
        # a later visit cannot quietly cost a different amount from the first.
        amounts = price_appointment(provider, services, promo=promo, points_off=points_off)
        self.discount = amounts.discount
        self.promo = promo
        self.points_to_spend = amounts.points_discount
        self.points_to_redeem = self.validated_data.get("redeem_points", 0)

        with transaction.atomic():
            booking = Booking.objects.create(
                customer=self.context["request"].user,
                provider=provider,
                staff=self.validated_data.get("staff_obj"),
                starts_at=starts_at,
                ends_at=ends_at,
                status=amounts.status,
                subtotal=amounts.subtotal,
                platform_fee=amounts.platform_fee,
                total=amounts.total,
                deposit=amounts.deposit,
                balance=amounts.balance,
                cancellation_window_hours=provider.cancellation_window_hours,
                late_cancel_fee_percent=provider.late_cancel_fee_percent,
                late_cancel_fee=amounts.late_cancel_fee,
                currency=amounts.currency,
                notes=self.validated_data.get("notes", ""),
            )
            BookingItem.objects.bulk_create(
                [BookingItem(booking=booking, **fields) for fields in booking_items(services)]
            )

            # Frozen onto the booking, inside the same transaction. A booking
            # that exists without its answers is a barber reading an appointment
            # as though nobody had said anything.
            record_answers(
                booking,
                self.validated_data.get("consultation_answers", {}),
                self.validated_data.get("consultation_questions", []),
            )

            # Inside the booking's transaction: a redemption that cannot be
            # written must roll the booking back, not leave points spent
            # against an appointment that does not exist.
            points_to_spend = getattr(self, "points_to_spend", 0)
            if points_to_spend:
                from promotions import loyalty as points_ledger

                points_ledger.spend(
                    customer=booking.customer,
                    provider=booking.provider,
                    booking=booking,
                    points=points_to_spend,
                )

            promo = getattr(self, "promo", None)
            if promo is not None:
                PromoRedemption.objects.create(
                    code=promo,
                    booking=booking,
                    discount=getattr(self, "discount", 0),
                )
                PromoCode.objects.filter(pk=promo.pk).update(times_used=promo.times_used + 1)

        return booking


class CancelBookingSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")


class WaitlistEntrySerializer(serializers.ModelSerializer):
    """A waitlist entry, as the customer sees their own."""

    provider_name = serializers.CharField(source="provider.display_name", read_only=True)
    service_name = serializers.CharField(source="service.name", read_only=True)
    staff_name = serializers.CharField(source="staff.name", read_only=True, default=None)

    class Meta:
        model = WaitlistEntry
        fields = [
            "id",
            "provider",
            "provider_name",
            "service",
            "service_name",
            "staff",
            "staff_name",
            "window_start",
            "window_end",
            "status",
            "created_at",
        ]
        read_only_fields = ["status", "created_at", "provider_name", "service_name", "staff_name"]


class WaitlistJoinSerializer(serializers.Serializer):
    """Ask to be told when something frees up."""

    provider = serializers.IntegerField()
    service = serializers.IntegerField()
    staff = serializers.IntegerField(required=False, allow_null=True)
    window_start = serializers.DateTimeField()
    window_end = serializers.DateTimeField()

    def validate(self, attrs: dict) -> dict:
        if attrs["window_start"] >= attrs["window_end"]:
            raise serializers.ValidationError(
                {"window_end": "The end of the window has to be after its start."}
            )

        if attrs["window_start"] <= timezone.now():
            raise serializers.ValidationError({"window_start": "That window has already started."})

        provider = get_object_or_404(ProviderProfile, pk=attrs["provider"])

        service = Service.objects.filter(
            pk=attrs["service"], provider=provider, is_active=True
        ).first()
        if service is None:
            # Same answer as a missing id, so this cannot be used to find out
            # which services another shop offers.
            raise serializers.ValidationError(
                {"service": "That service is not available at this shop."}
            )

        staff = None
        if attrs.get("staff") is not None:
            staff = Staff.objects.filter(
                pk=attrs["staff"], provider=provider, is_active=True
            ).first()
            if staff is None:
                raise serializers.ValidationError(
                    {"staff": "That person does not work at this shop."}
                )

        duplicate = WaitlistEntry.objects.filter(
            customer=self.context["request"].user,
            provider=provider,
            service=service,
            status__in=[WaitlistStatus.WAITING, WaitlistStatus.OFFERED],
        ).exists()
        if duplicate:
            raise serializers.ValidationError(
                "You are already on the waitlist for that service here."
            )

        attrs["provider_obj"] = provider
        attrs["service_obj"] = service
        attrs["staff_obj"] = staff
        return attrs

    def save(self, **kwargs) -> WaitlistEntry:
        return WaitlistEntry.objects.create(
            customer=self.context["request"].user,
            provider=self.validated_data["provider_obj"],
            service=self.validated_data["service_obj"],
            staff=self.validated_data.get("staff_obj"),
            window_start=self.validated_data["window_start"],
            window_end=self.validated_data["window_end"],
        )


class WaitlistOfferSerializer(serializers.ModelSerializer):
    """A slot being held for this customer, and how long they have."""

    shop_name = serializers.CharField(source="entry.provider.display_name", read_only=True)
    service_name = serializers.CharField(source="entry.service.name", read_only=True)
    staff_name = serializers.CharField(source="staff.name", read_only=True, default=None)
    seconds_left = serializers.SerializerMethodField()
    can_accept = serializers.SerializerMethodField()

    class Meta:
        model = WaitlistOffer
        fields = [
            "id",
            "shop_name",
            "service_name",
            "staff_name",
            "starts_at",
            "ends_at",
            "status",
            "expires_at",
            "seconds_left",
            "can_accept",
        ]

    def get_seconds_left(self, obj: WaitlistOffer) -> int:
        return max(0, int((obj.expires_at - timezone.now()).total_seconds()))

    def get_can_accept(self, obj: WaitlistOffer) -> bool:
        """Whether accepting would still succeed.

        The hold may have lapsed without the cleanup task having run, and
        offering a button that will be refused is worse than not offering it.
        """
        return obj.status == "pending" and obj.expires_at > timezone.now()


class WaitlistDeclineResultSerializer(serializers.Serializer):
    """What happened when someone let a held slot go.

    ``passed_on`` is the part worth sending: without it a customer who has
    already declined sits waiting to find out whether anybody took it.
    """

    declined = serializers.BooleanField()
    passed_on = serializers.BooleanField()


class WaitlistDeclineSerializer(serializers.Serializer):
    """Declining takes no arguments — the offer id says which one."""

    class Meta:
        pass


class RescheduleSerializer(serializers.Serializer):
    """Move a booking to a different time.

    ``accept_price_change`` is the customer agreeing to a price that moved
    since they booked. It is a separate, explicit field rather than something
    inferred, because agreeing to more money is not something a client should
    do by omission.
    """

    starts_at = serializers.DateTimeField()
    accept_price_change = serializers.BooleanField(default=False)
