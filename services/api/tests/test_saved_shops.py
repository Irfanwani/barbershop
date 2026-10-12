"""Saved shops.

The marketing site has always promised this. It is also the cheapest retention
feature available and the backbone of the rebooking work that comes later, so
it is worth doing properly rather than as a heart on a screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from accounts.models import SavedShop
from providers.models import ProviderProfile
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
PROVIDERS = f"{V1}/providers/"

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


@dataclass
class Session:
    user: Any
    client: Any
    token: str

    def auth(self) -> dict:
        return auth_header(self.token)


def a_customer(label: str = "customer") -> Session:
    user = make_user(_next_name(label))
    client, token = logged_in(user)
    return Session(user=user, client=client, token=token)


def a_shop(accepting: bool = True) -> ProviderProfile:
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner, display_name="Sharp Cuts Studio")
    make_service(profile, price=25000)
    profile.is_accepting_bookings = accepting
    profile.save(update_fields=["is_accepting_bookings"])
    return profile


class TestSaving:
    def test_a_customer_can_save_a_shop(self):
        customer, shop = a_customer(), a_shop()

        response = customer.client.post(f"{V1}/me/saved-shops/{shop.pk}/", {}, **customer.auth())

        assert response.status_code == 201, response.data
        assert SavedShop.objects.filter(customer=customer.user, provider=shop).exists()

    def test_saving_twice_is_idempotent(self):
        """A second tap on a heart is not an error worth showing anybody."""
        customer, shop = a_customer(), a_shop()

        first = customer.client.post(f"{V1}/me/saved-shops/{shop.pk}/", {}, **customer.auth())
        second = customer.client.post(f"{V1}/me/saved-shops/{shop.pk}/", {}, **customer.auth())

        assert first.status_code == second.status_code == 201
        assert first.data["id"] == second.data["id"]
        assert SavedShop.objects.filter(customer=customer.user, provider=shop).count() == 1

    def test_a_note_can_be_kept_with_it(self):
        customer, shop = a_customer(), a_shop()

        response = customer.client.post(
            f"{V1}/me/saved-shops/{shop.pk}/",
            {"note": "my usual place"},
            **customer.auth(),
        )

        assert response.data["note"] == "my usual place"
        assert SavedShop.objects.get(customer=customer.user).note == "my usual place"

    def test_saving_again_updates_the_note(self):
        customer, shop = a_customer(), a_shop()
        customer.client.post(
            f"{V1}/me/saved-shops/{shop.pk}/", {"note": "near the office"}, **customer.auth()
        )

        customer.client.post(
            f"{V1}/me/saved-shops/{shop.pk}/", {"note": "near home"}, **customer.auth()
        )

        assert SavedShop.objects.get(customer=customer.user).note == "near home"

    def test_unsaving_removes_it(self):
        customer, shop = a_customer(), a_shop()
        customer.client.post(f"{V1}/me/saved-shops/{shop.pk}/", {}, **customer.auth())

        response = customer.client.delete(f"{V1}/me/saved-shops/{shop.pk}/", **customer.auth())

        assert response.status_code == 204
        assert not SavedShop.objects.filter(customer=customer.user).exists()

    def test_unsaving_something_never_saved_is_fine(self):
        customer, shop = a_customer(), a_shop()
        response = customer.client.delete(f"{V1}/me/saved-shops/{shop.pk}/", **customer.auth())
        assert response.status_code == 204

    def test_you_only_see_your_own(self):
        customer, stranger, shop = a_customer(), a_customer("stranger"), a_shop()
        customer.client.post(f"{V1}/me/saved-shops/{shop.pk}/", {}, **customer.auth())

        assert len(stranger.client.get(f"{V1}/me/saved-shops/", **stranger.auth()).data) == 0
        assert len(customer.client.get(f"{V1}/me/saved-shops/", **customer.auth()).data) == 1

    def test_it_needs_a_signed_in_customer(self):
        shop = a_shop()
        response = client_anonymous().post(f"{V1}/me/saved-shops/{shop.pk}/", {})
        assert response.status_code in (401, 403)


class TestSavedShopsComeFirst:
    def test_browse_puts_saved_shops_first(self):
        customer = a_customer()
        a_shop()  # not saved
        saved = a_shop()
        customer.client.post(f"{V1}/me/saved-shops/{saved.pk}/", {}, **customer.auth())

        response = customer.client.get(PROVIDERS, **customer.auth())

        names = [row["display_name"] for row in response.data["results"]]
        assert names.index("Sharp Cuts Studio") == 0
        assert len(names) == 2

    def test_an_anonymous_browse_is_unaffected(self):
        a_shop()
        response = client_anonymous().get(PROVIDERS)

        assert all(row["is_saved"] is False for row in response.data["results"])

    def test_the_public_search_says_whether_a_shop_is_paused(self):
        """The marketing site renders a price, or "not taking bookings".

        This field was missing from the search response, so every shop on the
        public site rendered as paused. A test on the fields a client depends
        on is the only thing that catches it — the code reads fine.
        """
        a_shop(accepting=False)
        response = client_anonymous().get(PROVIDERS)

        assert response.data["results"][0]["is_accepting_bookings"] is False

    def test_an_open_shop_says_so(self):
        a_shop(accepting=True)
        response = client_anonymous().get(PROVIDERS)

        assert response.data["results"][0]["is_accepting_bookings"] is True

    def test_saved_is_reported_on_each_row(self):
        customer, shop = a_customer(), a_shop()
        customer.client.post(f"{V1}/me/saved-shops/{shop.pk}/", {}, **customer.auth())

        response = customer.client.get(PROVIDERS, **customer.auth())

        assert all(row["is_saved"] is True for row in response.data["results"])

    def test_one_customer_never_sees_anothers_saved_shops_first(self):
        mine, theirs = a_customer(), a_customer("theirs")
        their_shop = a_shop()
        theirs.client.post(f"{V1}/me/saved-shops/{their_shop.pk}/", {}, **theirs.auth())
        a_shop()

        response = mine.client.get(PROVIDERS, **mine.auth())

        assert all(row["is_saved"] is False for row in response.data["results"])


class TestAClosedShopIsStillSaved:
    def test_a_shop_that_stops_taking_bookings_still_appears(self):
        """Somebody's usual barber does not stop existing over a holiday."""
        customer, shop = a_customer(), a_shop()
        customer.client.post(f"{V1}/me/saved-shops/{shop.pk}/", {}, **customer.auth())

        shop.is_accepting_bookings = False
        shop.save(update_fields=["is_accepting_bookings"])

        response = customer.client.get(f"{V1}/me/saved-shops/", **customer.auth())

        assert len(response.data) == 1
        assert response.data[0]["provider"]["is_accepting_bookings"] is False

    def test_saving_does_not_bypass_the_pause(self):
        """Saving is a bookmark. It is not a way around a closed shop."""
        customer, shop = a_customer(), a_shop(accepting=False)

        response = customer.client.post(f"{V1}/me/saved-shops/{shop.pk}/", {}, **customer.auth())

        assert response.status_code == 201
        # Still cannot be booked.
        bookable = customer.client.post(
            f"{V1}/bookings/new/",
            {
                "provider": shop.pk,
                "services": [shop.services.first().pk],
                "starts_at": next_week_slot(),
            },
            **customer.auth(),
        )
        assert bookable.status_code >= 400

    def test_a_saved_shop_still_shows_its_current_price(self):
        """Not the price they saved it at — that would be worse than nothing."""
        customer, shop = a_customer(), a_shop()
        customer.client.post(f"{V1}/me/saved-shops/{shop.pk}/", {}, **customer.auth())

        service = shop.services.first()
        service.price = 40000
        service.save(update_fields=["price"])

        response = customer.client.get(f"{V1}/me/saved-shops/", **customer.auth())

        assert response.data[0]["provider"]["starting_price"] == 40000


def client_anonymous():
    from django.test import Client

    return Client()


def next_week_slot():
    from datetime import timedelta

    from django.utils import timezone

    when = timezone.localtime() + timedelta(days=3)
    return when.replace(hour=12, minute=0, second=0, microsecond=0).isoformat()
