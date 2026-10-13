"""Reading and clearing risk flags.

A provider looking at their own customers, and the one action anybody can take:
clearing a flag. The second exists because a flag that was once true being true
forever means a customer who fixed whatever it was has no way of showing that.
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsProvider
from providers.models import ProviderProfile
from risk import scoring
from risk.models import RiskFlag


def _profile(user) -> ProviderProfile | None:
    return ProviderProfile.objects.filter(user=user).first()


class CustomerRiskView(APIView):
    """Where a customer stands at your shop, and what you might do about it."""

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(
        operation_id="risk_customer",
        summary="A customer's record at your shop",
        description=(
            "Advisory. The suggested deposit is a recommendation, not a price: "
            "the deposit actually taken stays whatever the service says."
        ),
        parameters=[],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, customer_pk: int):
        profile = _profile(request.user)
        if profile is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        from django.contrib.auth import get_user_model

        customer = get_user_model().objects.filter(pk=customer_pk).first()
        if customer is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        payload = scoring.assess(customer, profile).as_payload()
        # The shop is looking at somebody who booked with them; the name is the
        # point of the screen.
        payload["customer_display_name"] = customer.display_name
        return Response(payload)


class RiskFlagClearView(APIView):
    """Let somebody past a bad month."""

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(
        operation_id="risk_clear_flag",
        summary="Clear a flag",
        description=(
            "Kept rather than deleted, so the record of what happened survives being forgiven."
        ),
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request, pk: int):
        profile = _profile(request.user)
        if profile is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        flag_row = RiskFlag.objects.filter(pk=pk, provider=profile).first()
        if flag_row is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        scoring.clear(flag_row, by=request.user)
        return Response({"id": flag_row.pk, "cleared": True})
