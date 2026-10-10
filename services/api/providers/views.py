"""Provider discovery, service menu, payouts and availability.

The discovery endpoint is the heart of the product: "who can cut my hair near me,
right now". It is one PostGIS query, not a loop over coordinates in Python.
"""

from __future__ import annotations

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import next_free_slot, slot_grid
from core.pagination import DefaultPagination
from core.permissions import IsProvider
from providers.models import ProviderProfile, Service
from providers.serializers import (
    PayoutSerializer,
    ProviderDetailSerializer,
    ProviderListSerializer,
    ProviderSelfSerializer,
    ProviderWriteSerializer,
    ServiceSerializer,
    service_type_choices,
)


def _m(value: str | None) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class ProviderListView(APIView):
    """Search providers.

    Filters are all optional and combine:

    ``?lat=&lng=``          search origin; results come back sorted nearest-first
                            with a ``distance_km`` on each row
    ``?radius_km=``         how far to look (default 25, max 100)
    ``?service_type=``      barbershop, hair_salon, ...
    ``?services=a,b``       only providers offering every one of these services
    ``?open_now=true``      currently inside their working hours
    ``?min_rating=``        ignore providers below this average
    ``?page=&page_size=``   pagination

    Without ``lat``/``lng`` the caller's saved customer location is used; with
    neither, results are returned unranked.
    """

    permission_classes = [IsAuthenticated]
    pagination_class = DefaultPagination

    def get(self, request):
        latitude = _m(request.query_params.get("lat"))
        longitude = _m(request.query_params.get("lng"))
        origin = None

        if latitude is not None and longitude is not None:
            origin = Point(longitude, latitude, srid=4326)
        else:
            profile = getattr(request.user, "customer_profile", None)
            if profile and profile.coords:
                origin = profile.coords

        queryset = ProviderProfile.objects.select_related("user").annotate(
            service_count=Count("services", filter=Q(services__is_active=True), distinct=True)
        )

        radius_km = min(_m(request.query_params.get("radius_km")) or 25, 100)

        if origin is not None:
            # Distance on a geography column is measured on a spheroid in metres.
            # A customer in Delhi should not be told the shop next door is 400 m
            # away because the earth was treated as flat.
            queryset = queryset.annotate(distance_metres=Distance("coords", origin)).filter(
                distance_metres__lte=radius_km * 1000
            )

        service_type = request.query_params.get("service_type")
        if service_type and service_type != "all":
            queryset = queryset.filter(service_type=service_type)

        wanted = [
            name.strip()
            for name in (request.query_params.get("services") or "").split(",")
            if name.strip()
        ]
        if wanted:
            # "offers every one of these" — count distinct matches and compare to
            # how many were asked for, so a provider offering two of the three
            # does not slip through.
            queryset = queryset.annotate(
                matched=Count(
                    "services__name",
                    filter=Q(services__name__in=wanted),
                    distinct=True,
                )
            ).filter(matched=len(wanted))

        if request.query_params.get("open_now") in {"1", "true", "True"}:
            now = timezone.localtime()
            queryset = queryset.filter(opening_time__lte=now.time(), closing_time__gte=now.time())

        min_rating = _m(request.query_params.get("min_rating"))
        if min_rating is not None:
            queryset = queryset.filter(rating_average__gte=min_rating)

        if request.query_params.get("available_today") in {"1", "true", "True"}:
            queryset = [profile for profile in queryset if next_free_slot(profile) is not None]
        else:
            queryset = list(queryset)

        if origin is not None:
            queryset.sort(key=lambda profile: profile.distance_metres)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ProviderListSerializer(page, many=True, context={"request": request})

        response = paginator.get_paginated_response(serializer.data)
        response.data["search_origin"] = (
            {"latitude": origin.y, "longitude": origin.x} if origin else None
        )
        response.data["radius_km"] = radius_km
        return response


class ProviderDetailView(APIView):
    """One provider in full, with their menu.

    The old ``getbarber/<pk>`` had no ownership check and returned the shop's
    exact coordinates to any authenticated caller.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk: int):
        profile = get_object_or_404(
            ProviderProfile.objects.select_related("user").prefetch_related("services"),
            pk=pk,
        )

        origin = None
        latitude, longitude = (
            _m(request.query_params.get("lat")),
            _m(request.query_params.get("lng")),
        )
        if latitude is not None and longitude is not None:
            origin = Point(longitude, latitude, srid=4326)
        else:
            customer_profile = getattr(request.user, "customer_profile", None)
            origin = customer_profile.coords if customer_profile else None

        if origin is not None:
            profile = (
                ProviderProfile.objects.select_related("user")
                .filter(pk=profile.pk)
                .annotate(distance_metres=Distance("coords", origin))
                .first()
            )

        return Response(ProviderDetailSerializer(profile, context={"request": request}).data)


@extend_schema(tags=["providers"])
class ServiceTypeListView(APIView):
    """The provider categories, for a filter chip row."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(service_type_choices())


class MyProviderView(APIView):
    """The caller's own shop record."""

    permission_classes = [IsAuthenticated, IsProvider]

    def get(self, request):
        profile = get_object_or_404(ProviderProfile, user=request.user)
        return Response(ProviderSelfSerializer(profile).data)

    def put(self, request):
        return self._update(request)

    def patch(self, request):
        return self._update(request)

    def _update(self, request):
        profile = get_object_or_404(ProviderProfile, user=request.user)
        serializer = ProviderWriteSerializer(
            profile, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProviderSelfSerializer(profile).data)


class MyPayoutView(APIView):
    """The provider's payout account. Account numbers are write-only."""

    permission_classes = [IsAuthenticated, IsProvider]

    def get(self, request):
        profile = get_object_or_404(ProviderProfile, user=request.user)
        payout = getattr(profile, "payout", None)
        if payout is None:
            return Response(
                {
                    "payout_registered": False,
                    "verification_status": None,
                    "message": "Add your bank details to receive payments.",
                }
            )
        return Response({**PayoutSerializer(payout).data, "payout_registered": True})

    def put(self, request):
        profile = get_object_or_404(ProviderProfile, user=request.user)
        serializer = PayoutSerializer(
            data=request.data,
            partial=True,
            context={"provider": profile},
        )
        serializer.is_valid(raise_exception=True)
        payout = serializer.save()

        from payments.services import register_fund_account

        register_fund_account(payout)
        return Response({**PayoutSerializer(payout).data, "payout_registered": True})


class MyServiceView(APIView):
    """Add, edit, retire and remove the provider's own menu items."""

    permission_classes = [IsAuthenticated, IsProvider]

    def _provider(self, request) -> ProviderProfile:
        return get_object_or_404(ProviderProfile, user=request.user)

    def get(self, request):
        profile = self._provider(request)
        services = Service.objects.filter(provider=profile)
        return Response(ServiceSerializer(services, many=True).data)

    def post(self, request):
        profile = self._provider(request)
        serializer = ServiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(provider=profile)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class MyServiceDetailView(APIView):
    permission_classes = [IsAuthenticated, IsProvider]

    def get_service(self, request, pk: int) -> Service:
        profile = get_object_or_404(ProviderProfile, user=request.user)
        # Scoped to the caller's own shop: the old update took a bare id and
        # changed whatever it pointed at, for any authenticated user.
        return get_object_or_404(Service, pk=pk, provider=profile)

    def get(self, request, pk: int):
        return Response(ServiceSerializer(self.get_service(request, pk)).data)

    def patch(self, request, pk: int):
        service = self.get_service(request, pk)
        serializer = ServiceSerializer(service, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk: int):
        """Retire a service.

        Deletes rather than 410s. The old endpoint returned ``410 GONE`` after a
        successful delete, which every client read as a failure.
        """
        service = self.get_service(request, pk)
        service.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AvailabilityView(APIView):
    """The provider's bookable slots for the next fortnight.

    Marked unavailable rather than omitted when a slot is taken, so the app can
    show a full day instead of a day that silently shortens.
    """

    permission_classes = [IsAuthenticated, IsProvider]

    def get(self, request, pk: int):
        from bookings.models import is_slot_available, provider_has_capacity

        profile = get_object_or_404(ProviderProfile, pk=pk, user=request.user)

        days = int(_m(request.query_params.get("days")) or 14)
        days = max(1, min(days, 30))

        slots = []
        for starts_at, ends_at in slot_grid(profile, days=days):
            free = is_slot_available(profile, starts_at, ends_at) and provider_has_capacity(
                profile, starts_at, ends_at
            )
            slots.append(
                {
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "is_available": free,
                    "price": None,
                }
            )

        return Response(
            {
                "provider": profile.id,
                "slot_interval_minutes": profile.slot_interval_minutes,
                "opening_time": profile.opening_time,
                "closing_time": profile.closing_time,
                "slots": slots,
            }
        )
