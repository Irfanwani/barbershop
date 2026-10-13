"""Asking for a spreadsheet.

The request returns immediately with a row to poll. A year of bookings is not
an HTTP response, and a shop that presses a button and watches a spinner for
four minutes presses it again - which is how a year-long export becomes six
year-long exports.
"""

from __future__ import annotations

from datetime import date

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsProvider
from exports import csv, tasks
from exports.models import ExportRequest, ExportStatus
from providers.models import ProviderProfile

#: How far back a request may reach. Enough for a tax year and a little more.
MAX_YEARS = 3


class ExportRequestSerializer(serializers.ModelSerializer):
    datasets = serializers.ListField(
        child=serializers.ChoiceField(choices=csv.ALL_DATASETS), required=False
    )

    class Meta:
        model = ExportRequest
        fields = [
            "id",
            "from_date",
            "to_date",
            "datasets",
            "status",
            "row_count",
            "failure_reason",
            "created_at",
            "sent_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "row_count",
            "failure_reason",
            "created_at",
            "sent_at",
        ]

    def validate(self, attrs):
        from_date: date = attrs.get("from_date") or getattr(self.instance, "from_date", None)
        to_date: date = attrs.get("to_date") or getattr(self.instance, "to_date", None)
        if from_date is None or to_date is None:
            raise serializers.ValidationError("Both dates are required.")
        if to_date < from_date:
            raise serializers.ValidationError("The end date cannot be before the start.")
        if (to_date - from_date).days > MAX_YEARS * 366:
            raise serializers.ValidationError(
                f"Exports cover at most {MAX_YEARS} years. Ask us for anything older."
            )
        return attrs


class ExportViewSetMixin(APIView):
    """Shared date parsing, kept out of the subclasses for clarity."""

    def _provider(self, request) -> ProviderProfile | None:
        return ProviderProfile.objects.filter(user=request.user).first()


class ExportRequestView(ExportViewSetMixin):
    """Ask for an export, and see how the ones before it went."""

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(
        operation_id="exports_request",
        summary="Ask for a spreadsheet",
        description=(
            "Queued and emailed. Poll the row for `status`; there is nothing to "
            "download afterwards, by design - a copy of your data sitting in "
            "storage is a copy somebody eventually forwards."
        ),
        request=ExportRequestSerializer,
        responses={202: ExportRequestSerializer},
    )
    def post(self, request):
        profile = self._provider(request)
        if profile is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        body = ExportRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        row = ExportRequest.objects.create(
            provider=profile,
            requested_by=request.user,
            from_date=body.validated_data["from_date"],
            to_date=body.validated_data["to_date"],
            datasets=body.validated_data.get("datasets") or list(csv.ALL_DATASETS),
            status=ExportStatus.QUEUED,
        )

        # .delay() rather than calling the function: the whole point is that
        # this response is immediate.
        tasks.run_export.delay(row.pk)

        return Response(ExportRequestSerializer(row).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        operation_id="exports_list",
        summary="Your export requests",
        responses={200: ExportRequestSerializer(many=True)},
    )
    def get(self, request):
        profile = self._provider(request)
        if profile is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        rows = ExportRequest.objects.filter(provider=profile)[:50]
        return Response(ExportRequestSerializer(rows, many=True).data)


class ExportRequestDetailView(ExportViewSetMixin):
    """One request, for polling."""

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(
        operation_id="exports_detail",
        summary="One export request",
        responses={200: ExportRequestSerializer},
    )
    def get(self, request, pk: int):
        profile = self._provider(request)
        if profile is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        row = get_object_or_404(ExportRequest, pk=pk, provider=profile)
        return Response(ExportRequestSerializer(row).data)
