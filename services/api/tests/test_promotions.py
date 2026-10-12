"""Discount codes.

A code is only worth having if the discount is worked out **server-side, at
quote time**, and the same answer comes back at checkout. If the client
computed it, the client could decide how much to take off.

Which also forces the awkward question: does the discount reduce the platform
fee? It does, and that is the right answer even though the platform ends up
funding part of its own promotion — a total the customer cannot reconcile from
the numbers on the screen is a worse outcome than a slightly cheaper fee.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from bookings.models import Booking
from promotions.models import (
    PromoCode,
    PromoError,
    PromoKind,
    PromoRedemption,
    PromoScope,
    discount_for,
    price,
    resolve,
)
from tests.factories import (
    auth_header,
    logged_in,
    make_profile,
    make_provider_user,
    make_service,
    make_user,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def a_customer():
    user = make_user(_next_name("customer"))
    make_profile(user)
    client, token = logged_in(user)
    return user, client, token


def a_shop():
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner, display_name="Sharp Cuts Studio")
    return profile


def a_code(**kwargs) -> PromoCode:
    defaults = {
        "code": "SAVE20",
        "kind": PromoKind.PERCENT,
        "value": 20,
        "scope": PromoScope.PLATFORM,
        "max_discount_percent": 50,
    }
    defaults.update(kwargs)
    return PromoCode.objects.create(**defaults)


def a_slot(days: int = 3):
    when = timezone.localtime() + timedelta(days=days)
    return when.replace(hour=12, minute=0, second=0, microsecond=0)


def quote(client, token, profile, service, code: str | None = None):
    body = {
        "provider": profile.pk,
        "services": [service.pk],
        "starts_at": a_slot().isoformat(),
    }
    if code is not None:
        body["promo_code"] = code
    return client.post(f"{V1}/bookings/quote/", body, **auth_header(token))


def book(client, token, profile, service, code: str | None = None):
    body = {
        "provider": profile.pk,
        "services": [service.pk],
        "starts_at": a_slot().isoformat(),
    }
    if code is not None:
        body["promo_code"] = code
    return client.post(f"{V1}/bookings/new/", body, **auth_header(token))


class TestTheArithmetic:
    def test_a_percentage_takes_that_much_off(self):
        code = a_code(value=20)
        assert discount_for(code, 10000) == 2000

    def test_a_fixed_amount_takes_that_much_off(self):
        code = a_code(kind=PromoKind.AMOUNT, value=5000)
        assert discount_for(code, 10000) == 5000

    def test_a_fixed_amount_cannot_exceed_the_basket(self):
        code = a_code(kind=PromoKind.AMOUNT, value=50000)
        assert discount_for(code, 10000) == 10000

    def test_a_discount_can_never_go_negative(self):
        code = a_code(value=100, max_discount_percent=100)
        breakdown = price(10000, code=code)
        assert breakdown.total >= 0
        assert breakdown.platform_fee >= 0

    def test_the_code_cannot_discount_past_its_own_cap(self):
        """A "90% off" code must not be able to give away the chair."""
        code = a_code(value=90, max_discount_percent=25)
        assert discount_for(code, 10000) == 2500

    def test_nothing_off_is_the_default(self):
        breakdown = price(10000)
        assert breakdown.discount == 0
        assert breakdown.total == breakdown.subtotal + breakdown.platform_fee


class TestTheFee:
    def test_the_discount_reduces_the_fee_base(self):
        """The question this feature exists to decide."""
        code = a_code(value=20)
        breakdown = price(10000, code=code)

        assert breakdown.fee_base == 8000
        assert breakdown.platform_fee == 80
        assert breakdown.full_fee == 100
        assert breakdown.total == 8080

    def test_and_the_customer_is_shown_the_fee_it_replaced(self):
        code = a_code(value=20)
        payload = price(10000, code=code).as_payload()

        # A total nobody can get to from the numbers on the screen is a
        # support ticket.
        assert payload["full_platform_fee"] > payload["platform_fee"]
        assert payload["full_platform_fee_display"] != payload["platform_fee_display"]

    def test_with_no_code_the_fee_is_the_full_fee(self):
        assert price(10000).full_fee == price(10000).platform_fee


class TestValidity:
    def test_an_expired_code_is_refused(self):
        code = a_code(expires_at=timezone.now() - timedelta(hours=1))
        assert code.usable_for(provider=a_shop(), service_ids=set()) is not None

    def test_an_exhausted_code_is_refused(self):
        code = a_code(max_uses=1, times_used=1)
        assert code.usable_for(provider=a_shop(), service_ids=set()) is not None

    def test_an_inactive_code_is_refused(self):
        code = a_code(is_active=False)
        assert code.usable_for(provider=a_shop(), service_ids=set()) is not None

    def test_a_shop_code_does_not_work_at_another_shop(self):
        mine, theirs = a_shop(), a_shop()
        code = a_code(scope=PromoScope.SHOP, provider=mine)

        assert code.covers(provider=mine, service_ids=set()) is True
        assert code.covers(provider=theirs, service_ids=set()) is False

    def test_a_service_code_only_covers_that_service(self):
        profile = a_shop()
        wanted = make_service(profile, name="Colour")
        other = make_service(profile, name="Trim")
        code = a_code(scope=PromoScope.SERVICE, service=wanted)

        assert code.covers(provider=profile, service_ids={wanted.pk}) is True
        assert code.covers(provider=profile, service_ids={other.pk}) is False

    def test_an_unknown_code_says_so(self):
        with pytest.raises(PromoError):
            resolve("NOSUCHCODE", provider=a_shop(), service_ids=set())

    def test_codes_are_case_insensitive(self):
        """Somebody typing a code into a phone will get the case wrong."""
        a_code(code="Save20")
        assert resolve("save20", provider=a_shop(), service_ids=set()) is not None

    def test_surrounding_whitespace_is_forgiven(self):
        a_code(code="SAVE20")
        assert resolve("  SAVE20 ", provider=a_shop(), service_ids=set()) is not None

    def test_no_code_is_not_an_error(self):
        assert resolve(None, provider=a_shop(), service_ids=set()) is None


class TestAtQuote:
    def test_the_quote_applies_the_code(self):
        _user, client, token = a_customer()
        profile = a_shop()
        service = make_service(profile, price=10000)
        a_code(value=20)

        response = quote(client, token, profile, service, "SAVE20")

        assert response.status_code == 200, response.data
        assert response.data["discount"] == 2000
        assert response.data["platform_fee"] == 80
        assert response.data["full_platform_fee"] == 100
        assert response.data["total"] == 8080
        assert response.data["promo_code"] == "SAVE20"

    def test_an_expired_code_is_refused_at_quote(self):
        _user, client, token = a_customer()
        profile = a_shop()
        service = make_service(profile, price=10000)
        a_code(expires_at=timezone.now() - timedelta(minutes=1))

        response = quote(client, token, profile, service, "SAVE20")

        assert response.status_code >= 400
        assert "expired" in str(response.data).lower()

    def test_a_quote_with_no_code_is_unchanged(self):
        _user, client, token = a_customer()
        profile = a_shop()
        service = make_service(profile, price=10000)

        response = quote(client, token, profile, service)

        assert response.data["discount"] == 0
        assert response.data["total"] == response.data["subtotal"] + response.data["platform_fee"]


class TestAtCheckout:
    def test_the_booking_gets_the_discounted_total(self):
        _user, client, token = a_customer()
        profile = a_shop()
        service = make_service(profile, price=10000)
        a_code(value=20)

        response = book(client, token, profile, service, "SAVE20")

        assert response.status_code == 201, response.data
        booking = Booking.objects.get(reference=response.data["reference"])
        assert booking.total == 8080
        assert booking.subtotal == 10000

    def test_an_expired_code_is_refused_at_checkout(self):
        """Between quoting and paying is exactly when one expires."""
        _user, client, token = a_customer()
        profile = a_shop()
        service = make_service(profile, price=10000)
        a_code(expires_at=timezone.now() + timedelta(minutes=1))

        assert quote(client, token, profile, service, "SAVE20").status_code == 200

        PromoCode.objects.filter(code="SAVE20").update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        response = book(client, token, profile, service, "SAVE20")

        assert response.status_code >= 400
        assert Booking.objects.count() == 0

    def test_the_use_is_recorded(self):
        _user, client, token = a_customer()
        profile = a_shop()
        service = make_service(profile, price=10000)
        code = a_code(value=20, max_uses=2)

        book(client, token, profile, service, "SAVE20")

        redemption = PromoRedemption.objects.get()
        assert redemption.discount == 2000
        assert PromoCode.objects.get(pk=code.pk).times_used == 1

    def test_a_quoted_code_and_a_paid_code_agree(self):
        """The whole point of sharing one pricing function."""
        _user, client, token = a_customer()
        profile = a_shop()
        service = make_service(profile, price=10000)
        a_code(value=20)

        quoted = quote(client, token, profile, service, "SAVE20").data
        paid = book(client, token, profile, service, "SAVE20").data

        assert paid["total"] == quoted["total"]
        assert paid["platform_fee"] == quoted["platform_fee"]

    def test_the_usage_cap_is_enforced(self):
        _user, client, token = a_customer()
        profile = a_shop()
        service = make_service(profile, price=10000)
        a_code(value=20, max_uses=1)

        assert book(client, token, profile, service, "SAVE20").status_code == 201

        # A different slot, same single use.
        when = a_slot(5)
        response = client.post(
            f"{V1}/bookings/new/",
            {
                "provider": profile.pk,
                "services": [service.pk],
                "starts_at": when.isoformat(),
                "promo_code": "SAVE20",
            },
            **auth_header(token),
        )
        assert response.status_code >= 400
        assert "used up" in str(response.data).lower()


class TestTheClientCannotChoose:
    def test_a_client_sent_amount_is_ignored(self):
        _user, client, token = a_customer()
        profile = a_shop()
        service = make_service(profile, price=10000)

        response = client.post(
            f"{V1}/bookings/new/",
            {
                "provider": profile.pk,
                "services": [service.pk],
                "starts_at": a_slot().isoformat(),
                "discount": 9000,
                "total": 100,
            },
            **auth_header(token),
        )

        assert response.status_code == 201, response.data
        booking = Booking.objects.get(reference=response.data["reference"])
        assert booking.total > 100
        assert not PromoRedemption.objects.exists()
