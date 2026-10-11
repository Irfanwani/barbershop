"""Order placement, payment and collection.

Stock is decremented inside the same transaction that creates the order, and
checked there too. Checking at the API boundary and decrementing later is a
race: two customers adding the last bottle both see "in stock" and both succeed.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.db.models import F

from catalog.models import Inventory, Order, OrderStatus, Product
from catalog.serializers import OrderCreateSerializer
from core.money import compute_platform_fee

logger = logging.getLogger(__name__)


class OutOfStock(Exception):
    """Raised when stock moves between validation and checkout."""


def create_order(*, customer, serializer: OrderCreateSerializer) -> Order:
    """Price a basket server-side and create the order.

    The serializer has already validated that stock exists. This re-checks under
    a row lock, because "exists" was true a moment ago and may not be now.
    """
    provider = serializer.validated_data["provider_obj"]
    items = serializer.validated_data["items"]
    product_ids = [item["product"] for item in items]

    with transaction.atomic():
        # `select_for_update` on the inventory rows: two checkouts for the last
        # bottle queue here rather than both proceeding.
        inventory = {
            row.product_id: row
            for row in Inventory.objects.select_for_update()
            .select_related("product")
            .filter(provider=provider, product_id__in=product_ids)
        }

        missing = set(product_ids) - set(inventory)
        if missing:
            raise OutOfStock("One of those products is no longer sold here.")

        lines = []
        for item in items:
            row = inventory[item["product"]]
            if not row.product.is_active or not row.is_available:
                raise OutOfStock(f"{row.product.name} is no longer available.")
            if row.quantity < item["quantity"]:
                raise OutOfStock(f"Only {row.quantity} of {row.product.name} left.")

            lines.append(
                {
                    "product": row.product,
                    "name": row.product.name,
                    "unit_price": row.product.price,
                    "quantity": item["quantity"],
                }
            )

        subtotal = sum(line["unit_price"] * line["quantity"] for line in lines)
        fee = compute_platform_fee(subtotal, settings.PLATFORM_FEE_PERCENT)

        order = Order.objects.create(
            customer=customer,
            provider=provider,
            status=OrderStatus.PENDING,
            subtotal=subtotal,
            platform_fee=fee,
            total=subtotal + fee,
            notes=serializer.validated_data.get("notes", ""),
        )

        from catalog.models import OrderLine

        OrderLine.objects.bulk_create(
            [
                OrderLine(
                    order=order,
                    product=line["product"],
                    # Frozen, so a price change tomorrow does not change what
                    # this customer agreed to pay today.
                    name=line["name"],
                    unit_price=line["unit_price"],
                    quantity=line["quantity"],
                )
                for line in lines
            ]
        )

        Inventory.objects.filter(provider=provider, product_id__in=product_ids).update(
            quantity=F("quantity") - sum(item["quantity"] for item in items)
        )

    logger.info("Order %s placed for %s", order.reference, provider.display_name)
    return order


def restore_stock(order: Order) -> None:
    """Put an order's stock back. Used when an order is cancelled or refunded."""
    lines = list(order.lines.select_related("product"))
    if not lines:
        return

    with transaction.atomic():
        for line in lines:
            Inventory.objects.filter(provider=order.provider, product=line.product).update(
                quantity=F("quantity") + line.quantity
            )
    logger.info("Restored stock for cancelled order %s", order.reference)


def catalogue_for(provider, *, search: str | None = None, category: str | None = None):
    """What one shop is selling, for its storefront."""
    rows = (
        Inventory.objects.select_related("product")
        .filter(provider=provider, is_available=True, product__is_active=True)
        .order_by("product__name")
    )

    if search:
        needle = search.strip()
        if needle:
            from django.db.models import Q

            rows = rows.filter(
                Q(product__name__icontains=needle)
                | Q(product__brand__icontains=needle)
                | Q(product__description__icontains=needle)
            )

    if category and category != "all":
        rows = rows.filter(product__category=category)

    return rows


def popular_products(limit: int = 8):
    """The most-ordered products, for the browse home.

    Ordered by units sold rather than by rating: a product nobody has bought has
    no rating, and a new listing would never appear however good it is.
    """
    from django.db.models import Sum

    from catalog.models import OrderLine

    sold = (
        OrderLine.objects.filter(
            order__status__in=[OrderStatus.PAID, OrderStatus.READY, OrderStatus.COLLECTED]
        )
        .values("product_id")
        .annotate(units_sold=Sum("quantity"))
        .order_by("-units_sold")
    )

    order = {row["product_id"]: index for index, row in enumerate(sold[:limit])}
    if not order:
        return Product.objects.none()

    # `filter()` would fall back to `Meta.ordering` (alphabetical) and lose the
    # popularity ranking, which is the entire point of the query.
    products = list(Product.objects.filter(pk__in=order, is_active=True))
    products.sort(key=lambda product: order[product.id])
    return products
