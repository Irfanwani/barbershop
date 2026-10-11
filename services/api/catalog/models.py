"""A product catalogue and the shops that sell from it.

Products are stock, not services. A haircut is a `providers.Service` with a
duration and a slot; a bottle of shampoo is a `catalog.Product` with a quantity
and no appointment. Keeping them apart matters because they have different
lifecycles: a service is priced by the provider and booked, a product is priced
by the shop and collected.

One inventory per (product, shop). A chain selling the same brand in three
places has three inventories with three stock levels, not one shared pool that
any of them can drain.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from core.models import TimeStampedModel
from core.money import format_minor
from core.references import generate_order_reference
from providers.models import ProviderProfile


class ProductCategory(models.TextChoices):
    HAIRCARE = "haircare", "Hair care"
    TOOLS = "tools", "Tools"
    STYLING = "styling", "Styling"
    SKINCARE = "skincare", "Skincare"
    OTHER = "other", "Other"


class Product(TimeStampedModel):
    """One thing a shop sells.

    ``price`` is the shop's own price in paise, before the platform fee, matching
    `providers.Service`. The marketplace charges the same 1% the booking flow
    does; two fee rates on one platform is a support call nobody enjoys.
    """

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="", max_length=1000)
    brand = models.CharField(max_length=80, blank=True, default="", db_index=True)
    category = models.CharField(
        max_length=32, choices=ProductCategory.choices, default=ProductCategory.HAIRCARE
    )

    price = models.PositiveIntegerField(help_text="Shop price in paise.")
    compare_at_price = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Was-price in paise, for showing a discount. Not charged.",
    )

    photo = models.ImageField(upload_to="catalog/", blank=True, null=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "catalog_product"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["brand"]),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def price_display(self) -> str:
        return format_minor(self.price)

    @property
    def is_discounted(self) -> bool:
        """Whether the was-price is a genuine discount rather than a lie.

        A compare-at price below the price being charged is not a discount; it is
        a data-entry mistake that makes the shop look dishonest.
        """
        return bool(self.compare_at_price and self.compare_at_price > self.price)


class Inventory(TimeStampedModel):
    """How much of a product one shop has.

    ``quantity`` is decremented at checkout rather than at cart-add, so two
    people adding the last bottle do not both succeed.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="inventory")
    provider = models.ForeignKey(
        ProviderProfile, on_delete=models.CASCADE, related_name="inventory"
    )

    quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    is_available = models.BooleanField(
        default=True,
        help_text="Whether the shop offers this at all. Lets you hide stock without deleting it.",
    )

    class Meta:
        db_table = "catalog_inventory"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "provider"], name="catalog_inventory_product_provider_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0), name="catalog_inventory_quantity_gte_0"
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "is_available"]),
            models.Index(fields=["product", "quantity"]),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} at {self.provider.display_name} ({self.quantity})"

    @property
    def is_in_stock(self) -> bool:
        return self.is_available and self.quantity > 0


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    READY = "ready", "Ready for collection"
    COLLECTED = "collected", "Collected"
    CANCELLED = "cancelled", "Cancelled"
    REFUNDED = "refunded", "Refunded"


class Order(TimeStampedModel):
    """A basket of products, to be paid for and collected in shop."""

    reference = models.CharField(
        max_length=16, unique=True, db_index=True, default=generate_order_reference
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders"
    )
    provider = models.ForeignKey(ProviderProfile, on_delete=models.PROTECT, related_name="orders")

    status = models.CharField(
        max_length=16, choices=OrderStatus.choices, default=OrderStatus.PENDING
    )

    # Frozen at checkout, exactly as a booking is. A product's price changing
    # tomorrow must not change what this customer agreed to pay today.
    subtotal = models.PositiveIntegerField(default=0)
    platform_fee = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="INR")

    notes = models.TextField(blank=True, default="", max_length=500)

    paid_at = models.DateTimeField(null=True, blank=True)
    collected_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "catalog_order"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["customer", "-created_at"]),
            models.Index(fields=["provider", "status"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.reference} ({self.status})"

    @property
    def total_display(self) -> str:
        return format_minor(self.total, self.currency)

    @property
    def can_be_paid(self) -> bool:
        return self.status == OrderStatus.PENDING

    @property
    def can_be_collected(self) -> bool:
        return self.status in {OrderStatus.PAID, OrderStatus.READY}


class OrderLine(models.Model):
    """One product on an order, priced at the moment it was placed."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_lines")

    name = models.CharField(max_length=120)
    unit_price = models.PositiveIntegerField(help_text="Price in paise when the order was placed.")
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "catalog_order_line"
        ordering = ["id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1), name="catalog_order_line_quantity_gte_1"
            ),
            models.UniqueConstraint(
                fields=["order", "product"], name="catalog_order_line_order_product_uniq"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quantity} x {self.name}"

    @property
    def line_total(self) -> int:
        return self.unit_price * self.quantity
