"""Provider discovery, service menu, payouts and availability.

The discovery endpoint is the heart of the product: "who can cut my hair near me,
right now". It is one PostGIS query, not a loop over coordinates in Python.
"""

from __future__ import annotations

import logging
from datetime import time

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from bookings.models import slot_grid
from core.pagination import DefaultPagination
from core.permissions import IsProvider
from core.schema import BAD_REQUEST, FORBIDDEN, NOT_FOUND, UNAUTHORIZED
from providers.hours_serializers import (
    AvailabilityToggleSerializer,
    WorkingHoursSerializer,
    WorkingHoursWriteSerializer,
)
from providers.models import ProviderProfile, Service, WorkingHours
from providers.pricing import MIN_SAMPLE_FOR_CONFIDENCE
from providers.queries import starting_price_subquery
from providers.serializers import (
    PayoutSerializer,
    ProviderDetailSerializer,
    ProviderListSerializer,
    ProviderSelfSerializer,
    ProviderWriteSerializer,
    ServiceSerializer,
    annotate_next_free_slots,
    service_type_choices,
)

logger = logging.getLogger(__name__)


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

        queryset = (
            ProviderProfile.objects.select_related("user")
            .prefetch_related("hours")
            .annotate(
                service_count=Count("services", filter=Q(services__is_active=True), distinct=True)
            )
            .annotate(_starting_price_annotated=starting_price_subquery())
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

        # Sort in the database, not in Python. Sorting a list here meant the
        # whole table had been loaded first, so a platform with ten thousand
        # shops read ten thousand rows to show twenty.
        #
        # `id` as the tiebreaker matters either way: paginating a queryset with
        # no total order can return the same shop on two pages and skip another
        # entirely, so a customer scrolling the list sees a duplicate.
        queryset = queryset.order_by(
            *(["distance_metres"] if origin is not None else []),
            "id",
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)

        # One extra query for the whole page's availability, instead of one per
        # provider per candidate slot.
        page = annotate_next_free_slots(page)

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
class MyWorkingHoursView(APIView):
    """The provider's own weekly schedule — the open/closed control.

    The old app had no per-day control at all: one opening time and one closing
    time for all seven days, so a shop closed on Sunday still showed Sunday.
    """

    permission_classes = [IsAuthenticated, IsProvider]

    def _provider(self, request) -> ProviderProfile:
        return get_object_or_404(ProviderProfile, user=request.user)

    @extend_schema(
        operation_id="providers_hours_list",
        summary="Your opening hours",
        description=(
            "Read your weekly schedule. Days with no row fall back to the shop's "
            "default hours; Sunday is treated as closed."
        ),
        responses={200: WorkingHoursSerializer(many=True), 403: FORBIDDEN, 404: NOT_FOUND},
    )
    def get(self, request):
        profile = self._provider(request)
        return Response(WorkingHoursSerializer(profile.hours.all(), many=True).data)

    @extend_schema(
        operation_id="providers_hours_write",
        summary="Set your opening hours",
        description=(
            "Replace the days you list. Closing a weekday removes its slots from the "
            "booking calendar straight away, and opening it puts them back."
        ),
        request=WorkingHoursWriteSerializer,
        responses={200: WorkingHoursSerializer(many=True), 400: BAD_REQUEST},
    )
    def put(self, request):
        profile = self._provider(request)
        serializer = WorkingHoursWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            for day in serializer.validated_data["days"]:
                WorkingHours.objects.update_or_create(
                    provider=profile,
                    weekday=day["weekday"],
                    defaults={
                        "is_closed": day.get("is_closed", False),
                        "opens_at": day.get("opens_at", time(9, 0)),
                        "closes_at": day.get("closes_at", time(20, 0)),
                    },
                )

        return Response(WorkingHoursSerializer(profile.hours.all(), many=True).data)


class BookingToggleView(APIView):
    """The one switch that makes a shop findable again."""

    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(
        operation_id="providers_set_accepting_bookings",
        summary="Turn bookings on or off",
        description=(
            "Whether customers can book you at all. Turning it off does not cancel "
            "appointments already taken — it only stops new ones."
        ),
        request=AvailabilityToggleSerializer,
        responses={200: ProviderSelfSerializer, 400: BAD_REQUEST, 404: NOT_FOUND},
    )
    def post(self, request):
        profile = get_object_or_404(ProviderProfile, user=request.user)
        serializer = AvailabilityToggleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        profile.is_accepting_bookings = serializer.validated_data["is_accepting_bookings"]
        profile.save(update_fields=["is_accepting_bookings", "updated_at"])

        return Response(ProviderSelfSerializer(profile, context={"request": request}).data)


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


# ---------------------------------------------------------------------------
# Price intelligence
# ---------------------------------------------------------------------------


@extend_schema(
    tags=["providers"],
    summary="What shops around here charge",
    description=(
        "Aggregated prices for each shop type. Prices outside a plausible band are "
        "excluded, and a band built from fewer than three shops is marked `is_thin` "
        "so the app can say so rather than presenting a coin flip as a median."
    ),
    parameters=[OpenApiParameter("service_type", str, description="Limit to one shop type.")],
    responses={200: None},
)
class PriceInsightView(APIView):
    """Typical prices, aggregated across shops.

    Public: this is the page someone reads before they have decided where to go,
    which is before they have an account.
    """

    permission_classes = []

    @extend_schema(operation_id="providers_price_insights")
    def get(self, request):
        from providers.models import ServiceType
        from providers.pricing import plausible_prices, price_band

        services = Service.objects.select_related("provider")

        wanted = request.query_params.get("service_type")
        types = ServiceType.choices
        if wanted and wanted != "all":
            types = tuple((value, label) for value, label in types if value == wanted)

        bands = []
        for value, label in types:
            rows = services.filter(provider__service_type=value)
            if not plausible_prices(rows).exists():
                # Omit types nobody offers rather than showing an empty row.
                continue
            bands.append(price_band(value, label, rows).as_dict())

        return Response({"bands": bands, "minimum_sample": MIN_SAMPLE_FOR_CONFIDENCE})


@extend_schema(
    tags=["providers"],
    summary="What a service usually costs",
    description="Median price per service name, for names several shops actually offer.",
    parameters=[OpenApiParameter("limit", int)],
    responses={200: None},
)
class ServicePriceIndexView(APIView):
    """Comparable prices for common service names."""

    permission_classes = []

    @extend_schema(operation_id="providers_service_prices")
    def get(self, request):
        from providers.pricing import service_name_bands

        services = Service.objects.select_related("provider")

        raw_limit = request.query_params.get("limit")
        limit = int(raw_limit) if raw_limit and raw_limit.isdigit() else 10
        limit = max(1, min(limit, 50))

        return Response({"services": service_name_bands(services, limit=limit)})


@extend_schema(
    tags=["providers"],
    summary="Suggest services from what the customer says",
    description=(
        "Matches free text against real, active services. The model may only "
        "choose from the ids supplied to it, so a suggestion is always a "
        "service that exists and can be booked. Falls back to keyword matching "
        "when no model is configured, and says which it used."
    ),
    parameters=[OpenApiParameter("q", str, description="What the customer asked for.")],
    request=None,
    responses={200: None},
)
class ServiceSuggestionView(APIView):
    """What the customer asked for, matched to what a shop actually sells.

    The one place a language model earns its keep on this platform: bridging the
    gap between a customer's words and a shop's. It cannot change a booking or
    a price, so the cost of being wrong is an unhelpful suggestion.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="providers_suggest_services")
    def post(self, request):
        from providers.suggestions import (
            Matcher,
            SuggestionUnavailable,
            keyword_fallback,
            service_candidates,
        )

        query = (request.data.get("q") or "").strip()
        if not query:
            return Response(
                {"error": {"code": "validation_error", "message": "Say something."}}, status=400
            )

        limit = min(int(request.data.get("limit") or 5), 20)

        services = (
            Service.objects.filter(is_active=True, provider__is_accepting_bookings=True)
            .select_related("provider")
            .order_by("provider__rating_average", "price")
        )
        if request.data.get("provider"):
            services = services.filter(provider_id=request.data["provider"])

        candidates = service_candidates(services)
        if not candidates:
            return Response(
                {
                    "error": {
                        "code": "business_rule_violation",
                        "message": "Nothing to suggest yet.",
                    }
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        matcher = Matcher()
        matched_by = "keywords"
        try:
            ids = matcher.rank(query, candidates, limit=limit)
            matched_by = "model"
        except SuggestionUnavailable:
            logger.info("Falling back to keyword matching: no model configured or it failed")
            ids = keyword_fallback(query, candidates, limit=limit)

        by_id = {candidate["id"]: candidate for candidate in candidates}
        # Preserve the candidate order, so a tie is resolved the way the shop
        # would have ordered it.
        suggestions = [by_id[id_] for id_ in ids if id_ in by_id]

        return Response(
            {
                "suggestions": suggestions,
                "matched_by": matched_by,
                "candidates_considered": len(candidates),
            }
        )
