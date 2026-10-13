"""What a provider has earned, and asking for it."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsProvider
from core.schema import BAD_REQUEST, FORBIDDEN, NOT_FOUND
from payments.ledger import balance_for
from payments.models import LedgerEntry
from providers.models import ProviderProfile


class WithdrawalSerializer(serializers.Serializer):
    """Ask for money to go to the bank.

    Amount is optional and defaults to everything cleared, which is what
    providers want 95% of the time.
    """

    amount = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Defaults to everything cleared. Pending earnings cannot be paid early.",
    )


@extend_schema(
    tags=["providers"],
    summary="Your balance",
    description=(
        "What you have earned and what has been paid out. Derived from an append-only "
        "ledger, so every figure can be explained line by line."
    ),
    responses={200: OpenApiTypes.OBJECT, 403: FORBIDDEN, 404: NOT_FOUND},
)
class ProviderBalanceView(APIView):
    """The provider's position.

    The single number they care about, which there was nowhere to see before.
    """

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(operation_id="providers_balance")
    def get(self, request):
        provider = get_object_or_404(ProviderProfile, user=request.user)
        return Response(balance_for(provider).as_dict())


@extend_schema(
    tags=["providers"],
    summary="Your earnings, line by line",
    description="Append-only. Entries are never edited or deleted.",
    responses={200: OpenApiTypes.OBJECT, 403: FORBIDDEN, 404: NOT_FOUND},
)
class ProviderLedgerView(APIView):
    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(operation_id="providers_ledger")
    def get(self, request):
        from core.pagination import DefaultPagination

        provider = get_object_or_404(ProviderProfile, user=request.user)
        entries = LedgerEntry.objects.filter(provider=provider)

        paginator = DefaultPagination()
        page = paginator.paginate_queryset(entries, request, view=self)
        data = [
            {
                "id": entry.id,
                "kind": entry.kind,
                "status": entry.status,
                "amount": entry.amount,
                "amount_display": entry.amount_display,
                "reference": entry.reference,
                "description": entry.description,
                "created_at": entry.created_at,
            }
            for entry in page
        ]
        return paginator.get_paginated_response(data)


@extend_schema(
    tags=["providers"],
    summary="Withdraw your balance",
    description=(
        "Requests a transfer to your registered bank account. The balance drops "
        "immediately because the money has left ours either way; it is settled "
        "when the bank confirms."
    ),
    request=WithdrawalSerializer,
    responses={200: OpenApiTypes.OBJECT, 400: BAD_REQUEST, 403: FORBIDDEN, 404: NOT_FOUND},
)
class WithdrawalView(APIView):
    """Ask to be paid.

    Refused if the amount exceeds what has cleared, or if the bank account has
    not been verified. Either would mean moving money on a promise.
    """

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(operation_id="providers_withdraw")
    def post(self, request):
        from payments.settle import WithdrawalError, request_withdrawal

        provider = get_object_or_404(ProviderProfile, user=request.user)

        serializer = WithdrawalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = request_withdrawal(provider, amount=serializer.validated_data.get("amount"))
        except WithdrawalError as exc:
            return Response(
                {"error": {"code": "business_rule_violation", "message": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "withdrawal": result,
                "balance": balance_for(provider).as_dict(),
            }
        )
