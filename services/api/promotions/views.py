"""Points: the balance, and a redemption applied at quote and checkout."""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import Booking
from promotions import loyalty
from promotions.models import LoyaltyLedgerEntry, LoyaltyPolicy


class RedemptionSerializer(serializers.Serializer):
    #: Points to spend. The server works out what that is worth and caps it.
    points = serializers.IntegerField(min_value=0, required=False, default=0)


class PointsBalanceView(APIView):
    """What this customer has, and what of it is about to lapse."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="promotions_points_balance",
        summary="Your points balance",
        description=(
            "Expiring points are counted separately, because a balance nobody "
            "warns you about is a balance that arrives at zero on its own."
        ),
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        return Response(loyalty.balance(request.user).as_payload())


class PointsHistoryView(APIView):
    """Every movement, in words. A balance you cannot explain is not trusted."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="promotions_points_history",
        summary="Your points history",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        entries = LoyaltyLedgerEntry.objects.filter(customer=request.user).select_related(
            "provider"
        )
        return Response(
            {
                "entries": [
                    {
                        "id": entry.pk,
                        "points": entry.points,
                        "reason": entry.reason,
                        "shop": entry.provider.display_name if entry.provider else None,
                        "created_at": entry.created_at,
                        "expires_at": entry.expires_at,
                    }
                    for entry in entries
                ]
            }
        )


class PointsSettingsView(APIView):
    """What a shop awards, and how much of a booking points may cover."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="promotions_points_settings",
        summary="Your loyalty settings",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        provider = getattr(request.user, "provider_profile", None)
        if provider is None:
            return Response({"enabled": False})

        policy = loyalty.policy_for(provider)
        if policy is None:
            return Response(
                {
                    "enabled": False,
                    "points_per_booking": 0,
                    "validity_days": 365,
                    "max_redemption_percent": 20,
                }
            )

        return Response(
            {
                "enabled": policy.points_per_booking > 0,
                "points_per_booking": policy.points_per_booking,
                "validity_days": policy.validity_days,
                "max_redemption_percent": policy.max_redemption_percent,
            }
        )

    @extend_schema(
        operation_id="promotions_points_settings_update",
        summary="Change your loyalty settings",
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
    )
    def put(self, request):
        provider = getattr(request.user, "provider_profile", None)
        if provider is None:
            return Response(
                {"error": {"code": "forbidden", "message": "Providers only.", "details": None}},
                status=status.HTTP_403_FORBIDDEN,
            )

        from promotions.serializers import LoyaltyPolicySerializer

        body = LoyaltyPolicySerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)

        policy, _created = LoyaltyPolicy.objects.update_or_create(
            provider=provider, defaults=body.validated_data
        )

        return Response(
            {
                "enabled": policy.points_per_booking > 0,
                "points_per_booking": policy.points_per_booking,
                "validity_days": policy.validity_days,
                "max_redemption_percent": policy.max_redemption_percent,
            }
        )


class BookingPointsView(APIView):
    """How many points this booking may redeem, and what that is worth."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="promotions_booking_points",
        summary="Points usable on a booking",
        description=(
            "The cap is applied here as well as at redemption, so the number "
            "on the screen is the number that will be honoured."
        ),
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, reference: str):
        from django.shortcuts import get_object_or_404

        from bookings.views import visible_bookings

        booking = get_object_or_404(
            Booking.objects.filter(visible_bookings(request.user)).select_related("provider"),
            reference=reference,
        )

        usable = loyalty.points_spendable(request.user, booking)

        return Response(
            {
                "available": loyalty.balance(request.user).available,
                "usable_on_this_booking": usable,
                "worth_minor": usable * loyalty.POINTS_PER_MINOR,
                "total_minor": booking.total,
            }
        )
