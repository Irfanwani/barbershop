"""Serializers for the product catalogue and orders."""

from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from catalog.models import Inventory, Order, Product, ProductCategory
from core.money import compute_platform_fee, format_minor
from providers.models import ProviderProfile


class ProductSerializer(serializers.ModelSerializer):
    price_display = serializers.CharField(read_only=True)
    compare_at_price_display = serializers.SerializerMethodField()
    is_discounted = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "description",
            "brand",
            "category",
            "price",
            "price_display",
            "compare_at_price",
            "compare_at_price_display",
            "is_discounted",
            "photo",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_compare_at_price_display(self, obj: Product) -> str | None:
        if not obj.compare_at_price:
            return None
        return format_minor(obj.compare_at_price)

    def validate_category(self, value: str) -> str:
        if value not in ProductCategory.values:
            raise serializers.ValidationError("Choose a category from the list.")
        return value

    def validate_compare_at_price(self, value):
        """A was-price at or below the price is not a discount.

        Rejected rather than silently ignored: the alternative is a product page
        reading "was ₹300, now ₹200" that has quietly become "was ₹150".
        """
        if value in (None, ""):
            return None
        price = self.initial_data.get("price")
        if price is not None and value <= int(price):
            raise serializers.ValidationError(
                "The was-price has to be higher than the price you are charging."
            )
        return value

    def validate(self, attrs):
        # Also catches edits that lower `price` below an existing was-price.
        price = attrs.get("price", getattr(self.instance, "price", None))
        compare_at = attrs.get("compare_at_price", getattr(self.instance, "compare_at_price", None))
        if price is not None and compare_at and compare_at <= price:
            raise serializers.ValidationError(
                {"compare_at_price": "The was-price has to be higher than the price."}
            )
        return attrs


class InventorySerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    quantity = serializers.IntegerField(required=False, min_value=0)
    is_in_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Inventory
        fields = ["id", "product", "quantity", "is_available", "is_in_stock", "updated_at"]
        read_only_fields = ["updated_at"]


class ShopProductSerializer(serializers.Serializer):
    """A product as it appears in a shop's storefront, with that shop's stock.

    Reads an `Inventory` row rather than a `Product`: the same shampoo in three
    shops is three rows with three stock levels, and a catalogue endpoint that
    cannot say which one it is describing is not useful to a shopfront.
    """

    id = serializers.IntegerField(read_only=True)
    product = ProductSerializer(read_only=True)
    # The instance *is* the inventory row, so these resolve directly.
    quantity = serializers.IntegerField(read_only=True)
    is_in_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Inventory
        fields = ["id", "product", "quantity", "is_in_stock"]


class OrderLineSerializer(serializers.Serializer):
    """One line, requested by product id and quantity.

    No price is accepted. The price comes from the product row, exactly as a
    booking's price comes from the service row.
    """

    product = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=20)


class OrderCreateSerializer(serializers.Serializer):
    """Create an order from a basket.

    The provider is not in the request: a basket spans one shop, because
    fulfilment is collection from that shop and a customer cannot collect from
    two addresses in one trip.
    """

    provider = serializers.IntegerField()
    items = OrderLineSerializer(many=True, allow_empty=False)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")

    def validate_items(self, items):
        seen = [item["product"] for item in items]
        duplicates = {pid for pid in seen if seen.count(pid) > 1}
        if duplicates:
            raise serializers.ValidationError(
                "The same product is listed twice. Combine them into one line."
            )
        return items

    def validate(self, attrs):
        provider = ProviderProfile.objects.filter(pk=attrs["provider"]).first()
        if provider is None:
            raise serializers.ValidationError({"provider": "No such shop."})

        product_ids = [item["product"] for item in attrs["items"]]
        stocked = {
            row.product_id: row
            for row in Inventory.objects.select_related("product").filter(
                provider=provider, product_id__in=product_ids
            )
        }

        problems = []
        for item in attrs["items"]:
            row = stocked.get(item["product"])
            if row is None or not row.is_available:
                problems.append("That shop does not sell one of those.")
            elif not row.product.is_active:
                problems.append(f"{row.product.name} is no longer for sale.")
            elif row.quantity < item["quantity"]:
                problems.append(
                    f"Only {row.quantity} of {row.product.name} left."
                    if row.quantity
                    else f"{row.product.name} is out of stock."
                )

        if problems:
            raise serializers.ValidationError({"items": problems})

        attrs["provider_obj"] = provider
        return attrs

    def quote(self) -> dict:
        """Server-side pricing for the basket."""
        provider = self.validated_data["provider_obj"]
        items = self.validated_data["items"]

        rows = {
            inv.product_id: inv.product
            for inv in Inventory.objects.select_related("product").filter(
                provider=provider, product_id__in=[item["product"] for item in items]
            )
        }

        lines = [
            {
                "product": rows[item["product"]].id,
                "name": rows[item["product"]].name,
                "unit_price": rows[item["product"]].price,
                "quantity": item["quantity"],
                "line_total": rows[item["product"]].price * item["quantity"],
            }
            for item in items
        ]

        subtotal = sum(line["line_total"] for line in lines)
        fee = compute_platform_fee(subtotal, settings.PLATFORM_FEE_PERCENT)

        return {
            "lines": lines,
            "subtotal": subtotal,
            "platform_fee": fee,
            "total": subtotal + fee,
            "currency": "INR",
        }


class OrderSerializer(serializers.ModelSerializer):
    provider = serializers.SerializerMethodField()
    lines = serializers.SerializerMethodField()
    total_display = serializers.CharField(read_only=True)
    can_be_paid = serializers.BooleanField(read_only=True)
    can_be_collected = serializers.BooleanField(read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "reference",
            "provider",
            "status",
            "lines",
            "subtotal",
            "platform_fee",
            "total",
            "total_display",
            "currency",
            "notes",
            "paid_at",
            "collected_at",
            "cancelled_at",
            "can_be_paid",
            "can_be_collected",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def get_provider(self, obj: Order) -> dict:
        return {
            "id": obj.provider_id,
            "display_name": obj.provider.display_name,
            "address": obj.provider.address,
        }

    def get_lines(self, obj: Order) -> list[dict]:
        stored = getattr(obj, "_lines", None)
        if stored is not None:
            return stored
        return [
            {
                "product": line.product_id,
                "name": line.name,
                "unit_price": line.unit_price,
                "quantity": line.quantity,
                "line_total": line.unit_price * line.quantity,
            }
            for line in obj.lines.all()
        ]


# ---------------------------------------------------------------------------


class OrderStatusActionSerializer(serializers.Serializer):
    """Which transition the caller wants, as a string rather than a URL.

    The old appointments API accepted a bare status string and let the caller
    write any status at all. The permitted set is this enum, and the view checks
    it against the order's current status too.
    """

    action = serializers.ChoiceField(choices=["cancel", "ready", "collect"])
