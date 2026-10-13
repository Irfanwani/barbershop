"""Managing your own keys, and reading the usage that says whether to keep them.

The whole point of the screen is the secret that is shown exactly once. So the
create response carries it, and nothing else in this file ever can - there is
no endpoint that returns a key's secret, because there is nothing stored to
return.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api_keys.models import ApiKey
from api_keys.scopes import SCOPE_CHOICES


class ApiKeySerializer(serializers.ModelSerializer):
    """A key, without the parts that are not yours to see again.

    The secret is never on this serializer at all - not read-only, not ever.
    It appears once, in the create response, and that is the only place.
    """

    last_used_at = serializers.DateTimeField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = ApiKey
        fields = [
            "id",
            "name",
            "prefix",
            "scopes",
            "is_active",
            "last_used_at",
            "expires_at",
            "is_expired",
            "created_at",
        ]
        read_only_fields = ["id", "prefix", "last_used_at", "created_at"]


class ApiKeyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    scopes = serializers.ListField(
        child=serializers.ChoiceField(choices=[scope for scope, _ in SCOPE_CHOICES]),
        allow_empty=False,
    )
    expires_in_days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=730,
        help_text="Left out, the key does not expire. Revoking works either way.",
    )


class MyApiKeysView(APIView):
    """Your keys, and minting new ones."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="api_keys_list",
        summary="Your API keys",
        description="Secrets are not returned here. They are shown once, at creation.",
        responses={200: ApiKeySerializer(many=True)},
    )
    def get(self, request):
        keys = ApiKey.objects.filter(user=request.user)
        return Response(ApiKeySerializer(keys, many=True).data)

    @extend_schema(
        operation_id="api_keys_create",
        summary="Create an API key",
        description=(
            "Returns the full key once. It cannot be retrieved afterwards - only "
            "a salted hash is stored - so copy it now or mint a new one."
        ),
        request=ApiKeyCreateSerializer,
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        body = ApiKeyCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        expires_at = None
        if body.validated_data.get("expires_in_days"):
            expires_at = timezone.now() + timedelta(days=body.validated_data["expires_in_days"])

        key, full = ApiKey.issue(
            user=request.user,
            name=body.validated_data["name"],
            scopes=body.validated_data["scopes"],
            expires_at=expires_at,
        )

        payload = ApiKeySerializer(key).data
        payload["key"] = full
        return Response(payload, status=status.HTTP_201_CREATED)


class MyApiKeyDetailView(APIView):
    """One of your keys: rename it, narrow it, or revoke it."""

    permission_classes = [IsAuthenticated]

    def _get(self, request, pk: int) -> ApiKey | None:
        # Scoped to the caller, so somebody else's key is a 404 rather than a
        # 403. "It does not exist" and "it is not yours" are the same fact.
        return ApiKey.objects.filter(user=request.user, pk=pk).first()

    @extend_schema(
        operation_id="api_keys_update",
        summary="Change a key",
        description="Narrowing scopes takes effect on the very next request.",
        request=ApiKeySerializer,
        responses={200: ApiKeySerializer},
    )
    def patch(self, request, pk: int):
        key = self._get(request, pk)
        if key is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        data = ApiKeySerializer(key, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        data.save()
        return Response(data.data)

    @extend_schema(
        operation_id="api_keys_revoke",
        summary="Revoke a key",
        description=(
            "Effective immediately - not at the end of a session or when a cache "
            "expires. The row is kept so the usage history survives."
        ),
        responses={200: ApiKeySerializer},
    )
    def delete(self, request, pk: int):
        key = self._get(request, pk)
        if key is None:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # A flag, not a delete. Somebody deciding to stop trusting an
        # integration should not also delete the record that it once was used.
        key.is_active = False
        key.save(update_fields=["is_active", "updated_at"])
        return Response(ApiKeySerializer(key).data)


class ApiKeyUsageView(APIView):
    """Which of your keys are earning their keep.

    A key nobody has used in months is a key somebody should revoke, and this
    is the only way anybody can find that out.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="api_keys_usage",
        summary="Key usage",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        keys = ApiKey.objects.filter(user=request.user)
        cutoff = timezone.now() - timedelta(days=30)
        active = [key for key in keys if key.usable]

        return Response(
            {
                "keys": ApiKeySerializer(keys, many=True).data,
                "active_count": len(active),
                "unused_count": sum(1 for key in active if key.last_used_at is None),
                "idle_count": sum(
                    1
                    for key in active
                    if key.last_used_at is not None and key.last_used_at < cutoff
                ),
            }
        )
