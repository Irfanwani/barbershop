"""``/api/v1/products/`` — the catalogue, shop shelves, and orders."""

from django.urls import path

from catalog.views import (
    MyInventoryView,
    OrderActionView,
    OrderCreateView,
    OrderDetailView,
    OrderListView,
    OrderQuoteView,
    PopularProductListView,
    ProductCategoryListView,
    ProductDetailView,
    ProductListView,
    ShopOrderListView,
    ShopProductsView,
)

app_name = "catalog"

urlpatterns = [
    path("", ProductListView.as_view(), name="list"),
    path("types/", ProductCategoryListView.as_view(), name="categories"),
    path("popular/", PopularProductListView.as_view(), name="popular"),
    path("<int:pk>/", ProductDetailView.as_view(), name="detail"),
    # A shop's shelf. Mounted here rather than under /providers/ because it is a
    # listing, and the same list is served to anonymous callers.
    path("shops/<int:provider_pk>/", ShopProductsView.as_view(), name="shop-products"),
    # The caller's own shelf and orders.
    path("me/inventory/", MyInventoryView.as_view(), name="my-inventory"),
    path("me/orders/", OrderListView.as_view(), name="my-orders"),
    path("me/shop-orders/", ShopOrderListView.as_view(), name="shop-orders"),
    # Actions live beside the resource they act on.
    path("orders/quote/", OrderQuoteView.as_view(), name="order-quote"),
    path("orders/new/", OrderCreateView.as_view(), name="order-create"),
    path("orders/<str:reference>/", OrderDetailView.as_view(), name="order-detail"),
    path("orders/<str:reference>/action/", OrderActionView.as_view(), name="order-action"),
]
