"""Discount codes.

A code is only useful if the discount is worked out **server-side, at quote
time**, and the same answer is reproduced at checkout. If the client computed
it, the client could decide how much to take off, and "applied server-side" is
the whole security model of this feature.

Which also decides the awkward question: **does the discount reduce the platform
fee?**

If the fee is a percentage of the subtotal, a discount naturally reduces the
fee with it, and the platform quietly eats part of the promotion it just
funded. That is a real cost, but it is also what "20% off" means to a
customer, and quietly keeping the fee at its full amount would show a total
nobody can reconcile from the numbers on the screen.

So: the fee is calculated on the **discounted amount**, and the quote says so
in words, with the full fee that would have applied shown next to it. The
platform pays for its own promotions, and nobody has to guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel
from core.money import compute_platform_fee, format_minor


class PromoKind(models.TextChoices):
    PERCENT = "percent", "Percentage"
    AMOUNT = "amount", "Fixed amount"


class PromoScope(models.TextChoices):
    PLATFORM = "platform", "Any shop"
    SHOP = "shop", "One shop"
    SERVICE = "service", "One service"


class PromoCode(TimeStampedModel):
    """A code a customer can type.

    Scoped rather than global by default, because a shop running its own
    "staff20" should not be surprised when it works at a competitor, and
    because a platform-wide code needs somebody to own the risk of it.
    """

    code = models.CharField(max_length=32, unique=True, db_index=True)
    description = models.CharField(max_length=120, blank=True, default="")

    kind = models.CharField(max_length=8, choices=PromoKind.choices, default=PromoKind.PERCENT)
    #: Percent, or paise. One field for both, because a code is one of them at
    #: a time and a second nullable column is a second thing to get wrong.
    value = models.PositiveIntegerField()

    scope = models.CharField(max_length=8, choices=PromoScope.choices, default=PromoScope.PLATFORM)
    provider = models.ForeignKey(
        "providers.ProviderProfile",
        on_delete=models.CASCADE,
        related_name="promo_codes",
        null=True,
        blank=True,
    )
    service = models.ForeignKey(
        "providers.Service",
        on_delete=models.CASCADE,
        related_name="promo_codes",
        null=True,
        blank=True,
    )

    starts_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    #: None means unlimited.
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    times_used = models.PositiveIntegerField(default=0)

    #: A discount must never take a booking below zero. `max_discount_percent`
    #: caps how far off a particular basket may go, so "50% off" cannot become
    #: "50% off and then the fee is negative".
    max_discount_percent = models.PositiveSmallIntegerField(default=50)

    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "promotions_promocode"
        ordering = ["-created_at"]
        constraints = [
            # A percentage over 100 is nonsense; a fixed amount has no such
            # ceiling, which is what the second half of this says. The two
            # rules are one constraint because `value` is one column.
            models.CheckConstraint(
                condition=models.Q(kind="amount") | models.Q(value__lte=100),
                name="promotions_value_sane",
            ),
        ]

    def __str__(self) -> str:
        return self.code

    def save(self, *args, **kwargs):
        # Normalised on the way in rather than on the way out. Somebody typing
        # a code into a phone will get the case wrong, and a lookup that
        # silently misses is indistinguishable from "this code does not work".
        self.code = (self.code or "").strip().upper()
        return super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def is_exhausted(self) -> bool:
        return self.max_uses is not None and self.times_used >= self.max_uses

    def covers(self, *, provider, service_ids: set[int]) -> bool:
        """Whether this code applies to the basket at all."""
        if self.scope == PromoScope.SHOP:
            return self.provider_id == provider.pk
        if self.scope == PromoScope.SERVICE:
            return self.service_id in service_ids
        return True

    def usable_for(self, *, provider, service_ids: set[int]) -> str | None:
        """Why this code cannot be used, or None if it can.

        Returned as a sentence rather than a flag because each of these reads
        differently to a customer, and "invalid code" for an expired one is a
        lie they will check.
        """
        if not self.is_active:
            return "That code is no longer active."
        if self.is_expired:
            return "That code has expired."
        if self.is_exhausted:
            return "That code has been used up."
        if not self.covers(provider=provider, service_ids=service_ids):
            return "That code does not apply to this booking."
        return None


class PromoRedemption(models.Model):
    """One booking that used one code.

    Separate from ``times_used`` on the code because that counter cannot say
    *who* or *when*, and a discount nobody can reconcile is a discount somebody
    will eventually dispute.
    """

    code = models.ForeignKey(PromoCode, on_delete=models.CASCADE, related_name="redemptions")
    booking = models.OneToOneField(
        "bookings.Booking", on_delete=models.CASCADE, related_name="promo_redemption"
    )
    discount = models.PositiveIntegerField(help_text="In the smallest currency unit.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "promotions_promoredemption"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code.code} on {self.booking_id}"


class PromoError(Exception):
    """The code cannot be used, and the customer is owed the reason."""


@dataclass(frozen=True)
class PriceBreakdown:
    """What the customer is paying, and why.

    Carries every intermediate figure. A total nobody can get to from the
    numbers on the screen is a support ticket.
    """

    subtotal: int
    discount: int
    fee_base: int
    platform_fee: int
    total: int

    @property
    def full_fee(self) -> int:
        """The fee that would have applied with no code.

        Shown beside the real one so "you saved 20%" is checkable.
        """
        return compute_platform_fee(self.subtotal, settings.PLATFORM_FEE_PERCENT)

    def as_payload(self) -> dict:
        return {
            "currency": "INR",
            "subtotal": self.subtotal,
            "subtotal_display": format_minor(self.subtotal),
            "discount": self.discount,
            "discount_display": format_minor(self.discount),
            "platform_fee": self.platform_fee,
            "platform_fee_display": format_minor(self.platform_fee),
            # The fee the discount reduced, stated rather than implied.
            "full_platform_fee": self.full_fee,
            "full_platform_fee_display": format_minor(self.full_fee),
            "total": self.total,
            "total_display": format_minor(self.total),
        }


def discount_for(code: PromoCode, subtotal: int) -> int:
    """How much this code takes off.

    The percentage cap exists to stop a mistyped "90% off" giving away the
    chair. It does **not** apply to a fixed amount: a shop offering ₹500 off
    has said exactly what it means to offer, and quietly reducing that to the
    cap is the code not doing what it says. A fixed amount is bounded by the
    basket instead, which is the only bound that means anything.
    """
    if subtotal <= 0:
        return 0

    if code.kind == PromoKind.AMOUNT:
        return max(0, min(code.value, subtotal))

    percent = min(code.value, code.max_discount_percent)
    return max(
        0,
        min(
            int((Decimal(subtotal) * Decimal(percent) / Decimal(100)).quantize(Decimal("1"))),
            subtotal,
        ),
    )


def price(subtotal: int, *, code: PromoCode | None = None) -> PriceBreakdown:
    """Work out the whole thing from the subtotal and an optional code.

    The fee is taken on the **discounted** amount. The promotion is ours to
    fund, and a total the customer cannot reconcile from the screen is a
    worse outcome than a slightly cheaper fee.
    """
    discount = discount_for(code, subtotal) if code else 0
    fee_base = max(subtotal - discount, 0)
    platform_fee = compute_platform_fee(fee_base, settings.PLATFORM_FEE_PERCENT)

    return PriceBreakdown(
        subtotal=subtotal,
        discount=discount,
        fee_base=fee_base,
        platform_fee=platform_fee,
        total=fee_base + platform_fee,
    )


def resolve(code: str | None, *, provider, service_ids: set[int]) -> PromoCode | None:
    """Find a code and refuse it with a reason if it cannot be used."""
    if not code:
        return None

    cleaned = code.strip().upper()
    found = PromoCode.objects.filter(code=cleaned).first()
    if found is None:
        raise PromoError("That code does not exist.")

    reason = found.usable_for(provider=provider, service_ids=service_ids)
    if reason:
        raise PromoError(reason)

    return found


def apply(booking, code: PromoCode, discount: int) -> PromoRedemption:
    """Record the use, so the cap counts and the discount can be reconciled."""
    redemption = PromoRedemption.objects.create(code=code, booking=booking, discount=discount)
    PromoCode.objects.filter(pk=code.pk).update(times_used=code.times_used + 1)
    return redemption


def expires_in(code: PromoCode) -> datetime | None:
    return code.expires_at
