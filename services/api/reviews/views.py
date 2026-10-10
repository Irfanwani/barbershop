"""Review endpoints."""

from __future__ import annotations

from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import CompactPagination
from core.permissions import IsProvider
from reviews.models import Review
from reviews.serializers import (
    ReviewCreateSerializer,
    ReviewReplySerializer,
    ReviewSerializer,
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


class ReviewCreateView(APIView):
    """Leave a review of a provider."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ReviewCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        review = serializer.save()
        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)


class ReviewDetailView(APIView):
    """Read or delete one review."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk: int):
        review = get_object_or_404(
            Review.objects.select_related("customer", "provider"), pk=pk, is_hidden=False
        )
        return Response(ReviewSerializer(review).data)

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


class ReviewReplyView(APIView):
    """A provider replies publicly."""

    permission_classes = [IsAuthenticated, IsProvider]

    def post(self, request, pk: int):
        review = get_object_or_404(Review, pk=pk, provider__user=request.user)

        serializer = ReviewReplySerializer(data=request.data, instance=review)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(ReviewSerializer(review).data)
