"""``/api/v1/products/`` — the catalogue and the shops that sell from it."""

from __future__ import annotations

import logging

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Inventory, Order, OrderStatus, Product, ProductCategory
from catalog.serializers import (
    InventorySerializer,
    OrderCreateSerializer,
    OrderSerializer,
    OrderStatusActionSerializer,
    ProductSerializer,
    ShopProductSerializer,
)
from catalog.services import OutOfStock, create_order, popular_products, restore_stock
from core.pagination import DefaultPagination
from core.permissions import IsProvider
from core.schema import BAD_REQUEST, FORBIDDEN, NOT_FOUND, UNAUTHORIZED
from providers.models import ProviderProfile

logger = logging.getLogger(__name__)


@extend_schema(
    tags=["products"],
    summary="Browse products",
    description="Every active product across every shop. Paginated.",
    parameters=[
        OpenApiParameter("category", str, description="Filter by category."),
        OpenApiParameter("brand", str, description="Filter by brand."),
        OpenApiParameter("search", str, description="Search name, brand and description."),
        OpenApiParameter("page", int),
        OpenApiParameter("page_size", int),
    ],
    responses={200: ProductSerializer(many=True)},
)
class ProductListView(APIView):
    """The catalogue. Public: someone deciding where to go should not need an account."""

    permission_classes = []

    @extend_schema(operation_id="products_list")
    def get(self, request):
        products = Product.objects.filter(is_active=True)

        category = request.query_params.get("category")
        if category and category != "all":
            products = products.filter(category=category)

        brand = request.query_params.get("brand")
        if brand:
            products = products.filter(brand__iexact=brand)

        search = request.query_params.get("search")
        if search:
            from django.db.models import Q

            needle = search.strip()
            if needle:
                products = products.filter(
                    Q(name__icontains=needle)
                    | Q(brand__icontains=needle)
                    | Q(description__icontains=needle)
                )

        paginator = DefaultPagination()
        page = paginator.paginate_queryset(products, request, view=self)
        return paginator.get_paginated_response(ProductSerializer(page, many=True).data)


@extend_schema(
    tags=["products"],
    summary="One product",
    responses={200: ProductSerializer, 404: NOT_FOUND},
)
class ProductDetailView(APIView):
    permission_classes = []

    @extend_schema(operation_id="products_retrieve")
    def get(self, request, pk: int):
        product = get_object_or_404(Product, pk=pk, is_active=True)

        return Response(ProductSerializer(product).data)


@extend_schema(
    tags=["products"],
    summary="Popular right now",
    description="Ranked by units sold, not by rating: a new product has no rating.",
    responses={200: ProductSerializer(many=True)},
)
class PopularProductListView(APIView):
    permission_classes = []

    @extend_schema(operation_id="products_popular")
    def get(self, request):
        return Response(ProductSerializer(popular_products(), many=True).data)


@extend_schema(
    tags=["products"],
    summary="Categories",
    responses={200: OpenApiTypes.OBJECT},
)
class ProductCategoryListView(APIView):
    permission_classes = []

    @extend_schema(operation_id="products_categories")
    def get(self, request):
        return Response(
            [{"value": value, "label": label} for value, label in ProductCategory.choices]
        )


# ---------------------------------------------------------------------------
# A shop's storefront
# ---------------------------------------------------------------------------


@extend_schema(
    tags=["products"],
    summary="What a shop is selling",
    parameters=[
        OpenApiParameter("search", str),
        OpenApiParameter("category", str),
    ],
    responses={200: ShopProductSerializer(many=True)},
)
class ShopProductsView(APIView):
    """One shop's shelf.

    Public, because "does this shop sell what I need" is asked before booking.
    """

    permission_classes = []

    @extend_schema(operation_id="products_shop_list")
    def get(self, request, provider_pk: int):
        from catalog.services import catalogue_for

        provider = get_object_or_404(ProviderProfile, pk=provider_pk)
        rows = catalogue_for(
            provider,
            search=request.query_params.get("search"),
            category=request.query_params.get("category"),
        )

        return Response(ShopProductSerializer(rows, many=True).data)


@extend_schema(
    tags=["products"],
    summary="Your shelf",
    description="Add or adjust stock. Products themselves are the platform's catalogue.",
    request=InventorySerializer,
    responses={200: InventorySerializer, 404: NOT_FOUND},
)
class MyInventoryView(APIView):
    permission_classes = [IsAuthenticated, IsProvider]

    def _provider(self, request) -> ProviderProfile:
        return get_object_or_404(ProviderProfile, user=request.user)

    @extend_schema(operation_id="products_inventory_list", responses=InventorySerializer(many=True))
    def get(self, request):
        provider = self._provider(request)
        rows = Inventory.objects.filter(provider=provider).select_related("product")
        return Response(InventorySerializer(rows, many=True).data)

    @extend_schema(
        operation_id="products_inventory_set",
        request=InventorySerializer,
        responses={201: InventorySerializer, 400: BAD_REQUEST},
    )
    def post(self, request):
        provider = self._provider(request)
        serializer = InventorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product = request.data.get("product")
        if isinstance(product, dict):
            product = product.get("id")

        row, _created = Inventory.objects.update_or_create(
            provider=provider,
            product_id=product,
            defaults={
                "quantity": serializer.validated_data.get("quantity", 0),
                "is_available": serializer.validated_data.get("is_available", True),
            },
        )
        row = Inventory.objects.select_related("product").get(pk=row.pk)

        return Response(InventorySerializer(row).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


class OrderQueryMixin:
    def _order_for_user(self, request, reference: str) -> Order:
        """Fetch an order the caller is allowed to see.

        Visible to the customer who placed it and to the shop fulfilling it, and
        to nobody else. A caller who cannot see it gets a 404, not a 403: saying
        "exists, but not yours" confirms that a reference is real, which is
        itself a leak.
        """
        order = get_object_or_404(
            Order.objects.select_related("provider", "provider__user"),
            reference=reference.upper(),
        )
        if order.customer_id != request.user.pk and order.provider.user_id != request.user.pk:
            raise Http404("No such order.")
        return order


@extend_schema(
    tags=["orders"],
    summary="Create an order",
    description=(
        "Prices come from the product rows, not the request. Stock is decremented "
        "inside the same transaction, so the last unit cannot be sold twice."
    ),
    request=OrderCreateSerializer,
    responses={201: OrderSerializer, 400: BAD_REQUEST, 401: UNAUTHORIZED},
)
class OrderCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="orders_create")
    def post(self, request):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = create_order(customer=request.user, serializer=serializer)
        except OutOfStock as exc:
            return Response(
                {"error": {"code": "business_rule_violation", "message": str(exc)}},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["orders"],
    summary="Price a basket",
    description="What you would pay, without creating anything.",
    request=OrderCreateSerializer,
    responses={200: OpenApiTypes.OBJECT, 400: BAD_REQUEST},
)
class OrderQuoteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="orders_quote")
    def post(self, request):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.quote())


@extend_schema(
    tags=["orders"],
    summary="Your orders",
    parameters=[OpenApiParameter("page", int), OpenApiParameter("page_size", int)],
    responses={200: OrderSerializer(many=True)},
)
class OrderListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="orders_list")
    def get(self, request):
        orders = Order.objects.filter(customer=request.user).select_related("provider")

        state = request.query_params.get("status")
        if state and state != "all":
            orders = orders.filter(status=state)

        paginator = DefaultPagination()
        page = paginator.paginate_queryset(orders, request, view=self)
        return paginator.get_paginated_response(OrderSerializer(page, many=True).data)


@extend_schema(
    tags=["orders"],
    summary="One order",
    responses={200: OrderSerializer, 404: NOT_FOUND},
)
class OrderDetailView(OrderQueryMixin, APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="orders_retrieve")
    def get(self, request, reference: str):
        order = self._order_for_user(request, reference)

        return Response(OrderSerializer(order).data)


@extend_schema(
    tags=["orders"],
    summary="Orders for your shop",
    parameters=[
        OpenApiParameter("status", str),
        OpenApiParameter("page", int),
        OpenApiParameter("page_size", int),
    ],
    responses={200: OrderSerializer(many=True)},
)
class ShopOrderListView(APIView):
    permission_classes = [IsAuthenticated, IsProvider]

    @extend_schema(operation_id="orders_shop_list")
    def get(self, request):
        provider = get_object_or_404(ProviderProfile, user=request.user)
        orders = Order.objects.filter(provider=provider).select_related("provider")

        state = request.query_params.get("status")
        if state and state != "all":
            orders = orders.filter(status=state)

        paginator = DefaultPagination()
        page = paginator.paginate_queryset(orders, request, view=self)
        return paginator.get_paginated_response(OrderSerializer(page, many=True).data)


@extend_schema(
    tags=["orders"],
    summary="Move an order along",
    description="Cancel, mark ready, or mark collected.",
    request=OrderStatusActionSerializer,
    responses={200: OrderSerializer, 400: BAD_REQUEST, 403: FORBIDDEN, 404: NOT_FOUND},
)
class OrderActionView(OrderQueryMixin, APIView):
    """Order transitions.

    The permitted move depends on who you are and what state the order is in.
    A customer can cancel; only the shop can mark ready or collected; neither can
    move an order backwards.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="orders_action")
    def post(self, request, reference: str):
        order = self._order_for_user(request, reference)

        serializer = OrderStatusActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data["action"]

        is_owner = order.customer_id == request.user.pk
        is_shop = order.provider.user_id == request.user.pk

        if action == "cancel":
            if not is_owner and not is_shop:
                return self._denied()
            if order.status not in {OrderStatus.PENDING, OrderStatus.PAID}:
                return self._bad("This order can no longer be cancelled.")
            with transaction.atomic():
                order.status = OrderStatus.CANCELLED
                order.cancelled_at = timezone.now()
                order.save(update_fields=["status", "cancelled_at", "updated_at"])
                restore_stock(order)
        elif action == "ready":
            if not is_shop:
                return self._denied()
            if order.status != OrderStatus.PAID:
                return self._bad("Only a paid order can be marked ready.")
            order.status = OrderStatus.READY
            order.save(update_fields=["status", "updated_at"])
        else:  # collect
            if not is_shop:
                return self._denied()
            if order.status != OrderStatus.READY:
                return self._bad("Mark the order ready before collecting it.")
            order.status = OrderStatus.COLLECTED
            order.collected_at = timezone.now()
            order.save(update_fields=["status", "collected_at", "updated_at"])

        return Response(OrderSerializer(order).data)

    def _denied(self) -> Response:
        return Response(
            {"error": {"code": "permission_denied", "message": "Not your order."}},
            status=status.HTTP_403_FORBIDDEN,
        )

    def _bad(self, message: str) -> Response:
        return Response(
            {"error": {"code": "business_rule_violation", "message": message}},
            status=status.HTTP_400_BAD_REQUEST,
        )
