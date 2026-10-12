"""Review endpoints."""

from __future__ import annotations

from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.exceptions import BusinessRuleViolation
from core.pagination import CompactPagination
from core.permissions import IsProvider
from core.schema import BAD_REQUEST, FORBIDDEN, NOT_FOUND, UNAUTHORIZED
from reviews.models import Review, can_be_requested_removed
from reviews.requests import notify_provider
from reviews.serializers import (
    ReviewCreateSerializer,
    ReviewRemovalRequestSerializer,
    ReviewReplySerializer,
    ReviewSerializer,
)


@extend_schema(
    tags=["reviews"],
    summary="Read reviews",
    parameters=[
        OpenApiParameter("provider", int, description="Reviews for one shop."),
        OpenApiParameter("mine", bool, description="Reviews you have written."),
        OpenApiParameter("rating", int, description="1-5."),
    ],
    responses={
        200: OpenApiResponse(
            {
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "results": {"type": "array", "items": {"$ref": "#/components/schemas/Review"}},
                    "summary": {
                        "type": "object",
                        "properties": {
                            "average": {"type": "number", "nullable": True},
                            "total": {"type": "integer"},
                        },
                    },
                },
            },
            "A page of reviews, with a rating summary",
        ),
        401: UNAUTHORIZED,
    },
)
class ReviewListView(APIView):
    """Reviews for one provider, or the caller's own written reviews.

    ``?provider=<id>``  every visible review for a shop
    ``?mine=true``      reviews this user has written
    ``?rating=5``       only that star rating
    """

    permission_classes = [IsAuthenticated]
    pagination_class = CompactPagination

    def get_queryset(self):
        params = self.request.query_params
        queryset = Review.objects.filter(is_hidden=False).select_related("customer", "provider")

        if params.get("mine") in {"1", "true"}:
            queryset = queryset.filter(customer=self.request.user)
        elif params.get("provider"):
            queryset = queryset.filter(provider_id=params["provider"])

        rating = params.get("rating")
        if rating:
            queryset = queryset.filter(rating=rating)

        return queryset.order_by("-created_at")

    @extend_schema(operation_id="reviews_list")
    def get(self, request):
        queryset = self.get_queryset()

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)

        response = paginator.get_paginated_response(ReviewSerializer(page, many=True).data)
        stats = queryset.aggregate(average=Avg("rating"), total=Count("id"))
        response.data["summary"] = {
            "average": round(float(stats["average"]), 2) if stats["average"] else None,
            "total": stats["total"],
        }
        return response


@extend_schema(
    tags=["reviews"],
    summary="Leave a review",
    description=(
        "A review may be tied to a booking, in which case it must be yours and the "
        "appointment must be over. Ratings are constrained to 1-5 at the database, "
        "the serializer and the API."
    ),
    request=ReviewCreateSerializer,
    responses={201: ReviewSerializer, 400: BAD_REQUEST, 401: UNAUTHORIZED},
)
class ReviewCreateView(APIView):
    """Leave a review of a provider."""

    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="reviews_create")
    def post(self, request):
        serializer = ReviewCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        review = serializer.save()

        # The shop should hear about a review the same day it arrives. Reviews
        # are the main thing a provider cannot see coming, and an unanswered
        # one — especially a bad one — is worse than the review.
        notify_provider(review)

        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["reviews"],
    summary="Read or delete a review",
    description="You can delete your own; staff can delete any. Hidden reviews read as absent.",
    request=None,
    responses={200: ReviewSerializer, 204: None, 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
)
class ReviewDetailView(APIView):
    """Read or delete one review."""

    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="reviews_retrieve")
    def get(self, request, pk: int):
        review = get_object_or_404(
            Review.objects.select_related("customer", "provider"), pk=pk, is_hidden=False
        )
        return Response(ReviewSerializer(review).data)

    @extend_schema(operation_id="reviews_delete")
    def delete(self, request, pk: int):
        """Delete your own review.

        The old endpoint compared usernames rather than comparing objects, which
        worked right up until two people picked the same name.
        """
        review = get_object_or_404(Review, pk=pk)
        if review.customer_id != request.user.pk and not request.user.is_staff:
            raise PermissionDenied("You can only delete your own review.")
        review.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["reviews"],
    summary="Reply publicly as the provider",
    request=ReviewReplySerializer,
    responses={
        200: ReviewSerializer,
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
        403: FORBIDDEN,
        404: NOT_FOUND,
    },
)
class ReviewReplyView(APIView):
    """A provider replies publicly."""

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(operation_id="reviews_reply")
    def post(self, request, pk: int):
        review = get_object_or_404(Review, pk=pk, provider__user=request.user)

        serializer = ReviewReplySerializer(data=request.data, instance=review)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(ReviewSerializer(review).data)


@extend_schema(
    tags=["reviews"],
    summary="What a shop's reviews say",
    description=(
        "The rating picture — average, distribution, count — computed from real "
        "reviews, plus a written summary when there are enough of them. Falls back "
        "to the numbers alone when no model is configured."
    ),
    responses={200: None, 404: NOT_FOUND},
)
class ProviderSummaryView(APIView):
    """A shop's reviews, condensed.

    Public: someone deciding between two shops should not need an account to
    read what customers say about them.
    """

    permission_classes = []

    @extend_schema(operation_id="reviews_summary")
    def get(self, request, provider_pk: int):
        from providers.models import ProviderProfile
        from reviews.summaries import summarise_provider

        provider = get_object_or_404(ProviderProfile, pk=provider_pk)
        return Response(summarise_provider(provider))


class ReviewRemovalRequestView(APIView):
    """Ask for a review to come down.

    Abuse, and only abuse. A provider who could wave away a review by asking
    would have no reason to keep the shop's rating honest, so the reason is
    required and checked rather than optional.
    """

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(
        operation_id="reviews_request_removal",
        summary="Ask for a review to be removed",
        description=(
            "Only for abuse: harassment, spam, or a review about somebody "
            "else. Being rated badly is not a reason."
        ),
        request=ReviewRemovalRequestSerializer,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request, pk: int):
        review = get_object_or_404(Review.objects.select_related("provider__user"), pk=pk)
        if review.provider.user_id != request.user.pk:
            raise PermissionDenied("That review is not about your shop.")

        body = ReviewRemovalRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        # Checked against what was *submitted*, not what is stored. Reading it
        # off the instance asks whether a previous request was for abuse, which
        # is always False the first time and always True afterwards — so the
        # first report is refused and every later one is allowed.
        if not can_be_requested_removed(body.validated_data["reason"]):
            raise BusinessRuleViolation(
                "A review can only be reported for abuse — harassment, spam, or "
                "one that is not about this appointment."
            )

        review.removal_requested_reason = body.validated_data["reason"]
        review.removal_requested_at = timezone.now()
        review.save(
            update_fields=["removal_requested_reason", "removal_requested_at", "updated_at"]
        )

        return Response(
            {
                "requested": True,
                "reason": review.removal_requested_reason,
                "note": "A moderator will look at it. The review stays up until then.",
            }
        )
