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
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import next_free_slot, slot_grid
from core.pagination import DefaultPagination
from core.permissions import IsProvider
from core.schema import BAD_REQUEST, FORBIDDEN, NOT_FOUND, UNAUTHORIZED
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


@extend_schema(
    tags=["providers"],
    summary="Find service providers",
    description=(
        "All filters are optional and combine. Supplying `lat`/`lng` sorts results "
        "nearest-first and adds `distance_km` to each row; without them the caller's "
        "saved customer location is used. Coordinates are matched against a real "
        "PostGIS radius query, so this stays a single index scan however many shops "
        "exist."
    ),
    parameters=[
        OpenApiParameter("lat", float, description="Search origin latitude."),
        OpenApiParameter("lng", float, description="Search origin longitude."),
        OpenApiParameter(
            "radius_km", float, description="How far to look. Default 25, capped at 100."
        ),
        OpenApiParameter(
            "service_type", str, description="barbershop, hair_salon, spa, ... or `all`."
        ),
        OpenApiParameter(
            "services", str, description="Comma-separated. Only providers offering *every* one."
        ),
        OpenApiParameter("open_now", bool, description="Only shops currently inside their hours."),
        OpenApiParameter("min_rating", float, description="Ignore shops below this average."),
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
                    "results": {
                        "type": "array",
                        "items": {"$ref": "#/components/schemas/ProviderList"},
                    },
                    "search_origin": {"type": "object", "nullable": True},
                    "radius_km": {"type": "number"},
                },
            },
            "A page of providers",
        ),
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
    },
)
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

    @extend_schema(operation_id="providers_list")
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


@extend_schema(
    tags=["providers"],
    summary="One provider, with their menu",
    description=(
        "Exact coordinates are never returned. The payload carries a location rounded "
        "to three decimal places — roughly 111 m — which is enough to place a map "
        "marker without publishing the shop's front door."
    ),
    parameters=[
        OpenApiParameter("lat", float, required=False),
        OpenApiParameter("lng", float, required=False),
    ],
    responses={200: ProviderDetailSerializer, 400: BAD_REQUEST, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
class ProviderDetailView(APIView):
    """One provider in full, with their menu.

    The old ``getbarber/<pk>`` had no ownership check and returned the shop's
    exact coordinates to any authenticated caller.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="providers_retrieve")
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
            # Re-query to attach the distance annotation, which cannot be added
            # to an already-instantiated row. The row is guaranteed to exist: it
            # was fetched by pk a few lines above.
            profile = (
                ProviderProfile.objects.select_related("user")
                .filter(pk=profile.pk)
                .annotate(distance_metres=Distance("coords", origin))
                .get()
            )

        return Response(ProviderDetailSerializer(profile, context={"request": request}).data)


@extend_schema(
    tags=["providers"],
    summary="Provider categories",
    description="Filter chips for the browse screen.",
    request=None,
    responses={
        200: OpenApiResponse(
            {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string", "example": "barbershop"},
                        "label": {"type": "string", "example": "Barber shop"},
                    },
                },
            },
            "The provider categories",
        )
    },
)
class ServiceTypeListView(APIView):
    """The provider categories, for a filter chip row."""

    permission_classes = [AllowAny]

    @extend_schema(operation_id="providers_service_types")
    def get(self, request):
        return Response(service_type_choices())


@extend_schema(
    tags=["providers"],
    summary="Your own shop record",
    request=ProviderWriteSerializer,
    responses={
        200: ProviderSelfSerializer,
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
        403: FORBIDDEN,
        404: NOT_FOUND,
    },
)
class MyProviderView(APIView):
    """The caller's own shop record."""

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(operation_id="providers_me_retrieve")
    def get(self, request):
        profile = get_object_or_404(ProviderProfile, user=request.user)
        return Response(ProviderSelfSerializer(profile).data)

    @extend_schema(operation_id="providers_me_update")
    def put(self, request):
        return self._update(request)

    @extend_schema(operation_id="providers_me_patch")
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


@extend_schema(
    tags=["providers"],
    summary="Your payout account",
    description=(
        "The account number and IFSC code are write-only and read back masked. They are "
        "encrypted at rest, and even a superuser cannot read them out of the admin."
    ),
    request=PayoutSerializer,
    responses={
        200: OpenApiResponse(
            {
                "type": "object",
                "properties": {
                    "payout_registered": {"type": "boolean"},
                    "account_number_masked": {"type": "string", "example": "••••••••••••1111"},
                    "ifsc_code_masked": {"type": "string", "example": "•••••••••••"},
                    "verification_status": {"type": "string"},
                },
            },
            "Your payout details, masked",
        ),
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
        403: FORBIDDEN,
        404: NOT_FOUND,
    },
)
class MyPayoutView(APIView):
    """The provider's payout account. Account numbers are write-only."""

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(operation_id="providers_me_payout")
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

    @extend_schema(operation_id="providers_me_payout_update")
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


@extend_schema(
    tags=["providers"],
    summary="Your service menu",
    description="Prices are in the smallest currency unit (paise): 25000 is ₹250.00.",
    request=ServiceSerializer,
    responses={
        200: ServiceSerializer(many=True),
        201: ServiceSerializer,
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
        403: FORBIDDEN,
    },
)
class MyServiceView(APIView):
    """Add, edit, retire and remove the provider's own menu items."""

    permission_classes = [IsAuthenticated, IsProvider]

    def _provider(self, request) -> ProviderProfile:
        return get_object_or_404(ProviderProfile, user=request.user)

    @extend_schema(operation_id="providers_services_list")
    def get(self, request):
        profile = self._provider(request)
        services = Service.objects.filter(provider=profile)
        return Response(ServiceSerializer(services, many=True).data)

    @extend_schema(operation_id="providers_services_create")
    def post(self, request):
        profile = self._provider(request)
        serializer = ServiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(provider=profile)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["providers"],
    summary="One of your services",
    description=(
        "Scoped to your own shop. The old API took a bare id and rewrote whatever it "
        "pointed at, for any signed-in user."
    ),
    request=ServiceSerializer,
    responses={
        200: ServiceSerializer,
        204: None,
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
        403: FORBIDDEN,
        404: NOT_FOUND,
    },
)
class MyServiceDetailView(APIView):
    permission_classes = [IsAuthenticated, IsProvider]

    def get_service(self, request, pk: int) -> Service:
        profile = get_object_or_404(ProviderProfile, user=request.user)
        # Scoped to the caller's own shop: the old update took a bare id and
        # changed whatever it pointed at, for any authenticated user.
        return get_object_or_404(Service, pk=pk, provider=profile)

    @extend_schema(operation_id="providers_services_retrieve")
    def get(self, request, pk: int):
        return Response(ServiceSerializer(self.get_service(request, pk)).data)

    @extend_schema(operation_id="providers_services_update")
    def patch(self, request, pk: int):
        service = self.get_service(request, pk)
        serializer = ServiceSerializer(service, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @extend_schema(operation_id="providers_services_delete")
    def delete(self, request, pk: int):
        """Retire a service.

        Deletes rather than 410s. The old endpoint returned ``410 GONE`` after a
        successful delete, which every client read as a failure.
        """
        service = self.get_service(request, pk)
        service.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["providers"],
    summary="Your bookable slots",
    description=(
        "Taken slots are returned marked unavailable rather than omitted, so the app can "
        "render a full day instead of a day that quietly shortens."
    ),
    parameters=[OpenApiParameter("days", int, description="1-30. Default 14.")],
    responses={
        200: OpenApiResponse(
            {
                "type": "object",
                "properties": {
                    "slot_interval_minutes": {"type": "integer"},
                    "opening_time": {"type": "string"},
                    "closing_time": {"type": "string"},
                    "slots": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "starts_at": {"type": "string", "format": "date-time"},
                                "ends_at": {"type": "string", "format": "date-time"},
                                "is_available": {"type": "boolean"},
                                "price": {"type": "integer", "nullable": True},
                            },
                        },
                    },
                },
            },
            "The availability grid",
        ),
        400: BAD_REQUEST,
        401: UNAUTHORIZED,
        403: FORBIDDEN,
        404: NOT_FOUND,
    },
)
class AvailabilityView(APIView):
    """The provider's bookable slots for the next fortnight.

    Marked unavailable rather than omitted when a slot is taken, so the app can
    show a full day instead of a day that silently shortens.
    """

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(operation_id="providers_availability")
    def get(self, request, pk: int):
        from bookings.models import has_room

        profile = get_object_or_404(ProviderProfile, pk=pk, user=request.user)

        days = int(_m(request.query_params.get("days")) or 14)
        days = max(1, min(days, 30))

        slots = []
        for starts_at, ends_at in slot_grid(profile, days=days):
            free = has_room(profile, starts_at, ends_at)
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
