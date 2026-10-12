"""The public shop page.

A shop owner pastes this address into an Instagram bio, a WhatsApp status, a
printed leaflet. It has to work on a phone with no app installed and preview
usefully when pasted into a chat — which is why it is rendered by the server
rather than by the app or by the single-page site.
"""

from __future__ import annotations

import pytest

from tests.factories import make_profile, make_provider_user, make_service

pytestmark = pytest.mark.django_db

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def a_shop(name: str = "Sharp Cuts Studio", *, accepting: bool = True):
    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner, display_name=name)
    profile.is_accepting_bookings = accepting
    profile.save(update_fields=["is_accepting_bookings"])
    return profile


class TestTheAddress:
    def test_a_shop_gets_one_when_it_is_created(self):
        assert a_shop("Sharp Cuts Studio").slug == "sharp-cuts-studio"

    def test_two_shops_with_the_same_name_get_different_addresses(self):
        first = a_shop("Corner Barber")
        second = a_shop("Corner Barber")

        assert first.slug != second.slug
        assert second.slug == "corner-barber-2"

    def test_a_shop_with_no_usable_name_still_gets_one(self):
        owner = make_provider_user(_next_name("nameless"))
        profile = make_profile(owner, display_name="???")

        assert profile.slug

    def test_the_shop_can_choose_its_own(self):
        """The link gets printed on leaflets. It has to be memorable."""
        owner = make_provider_user(_next_name("custom"))
        profile = make_profile(owner, display_name="Sharp Cuts Studio")

        profile.slug = "ravi-the-barber"
        profile.save()

        assert profile.slug == "ravi-the-barber"
        profile.refresh_from_db()
        assert profile.slug == "ravi-the-barber"


class TestThePage:
    def test_it_renders_the_shop_with_its_prices(self, client):
        shop = a_shop()
        make_service(shop, name="Haircut", price=25000)
        make_service(shop, name="Beard trim", price=10000)

        response = client.get(f"/shops/{shop.slug}/")

        assert response.status_code == 200
        body = response.content.decode()
        assert "Sharp Cuts Studio" in body
        assert "Haircut" in body
        assert "₹250" in body
        assert "₹100" in body

    def test_it_needs_no_javascript(self, client):
        """A link somebody is excited about should not depend on a bundle."""
        shop = a_shop()
        make_service(shop)

        body = client.get(f"/shops/{shop.slug}/").content.decode()

        assert "<script" not in body
        assert 'href="/shops/' in body or "canonical" in body

    def test_it_links_somewhere_to_book(self, client):
        shop = a_shop()
        make_service(shop)

        body = client.get(f"/shops/{shop.slug}/").content.decode()

        assert "Book in the app" in body
        assert f"barbershop://shop/{shop.slug}" in body

    def test_it_previews_usefully_in_a_chat(self, client):
        """A preview of a bare address gets nobody to tap it."""
        shop = a_shop()
        make_service(shop, price=25000)

        body = client.get(f"/shops/{shop.slug}/").content.decode()

        assert '<meta property="og:title" content="Sharp Cuts Studio" />' in body
        assert '<meta property="og:type" content="business.business" />' in body
        assert "og:image" in body
        assert f"/shops/{shop.slug}/" in body

    def test_an_unknown_address_is_a_clean_404(self, client):
        assert client.get("/shops/there-is-no-shop-here/").status_code == 404

    def test_a_shop_with_no_services_still_renders(self, client):
        """An empty menu is a shop that has not set itself up, not an error."""
        shop = a_shop()
        response = client.get(f"/shops/{shop.slug}/")

        assert response.status_code == 200
        assert "Sharp Cuts Studio" in response.content.decode()

    def test_it_says_so_when_the_shop_is_paused(self, client):
        shop = a_shop(accepting=False)
        make_service(shop)

        body = client.get(f"/shops/{shop.slug}/").content.decode()

        assert "Not taking bookings" in body

    def test_it_lists_the_team(self, client):
        from providers.models import Staff

        shop = a_shop()
        make_service(shop)
        Staff.objects.create(provider=shop, name="Ravi")
        Staff.objects.create(provider=shop, name="Priya")
        Staff.objects.create(provider=shop, name="Gone", is_active=False)

        body = client.get(f"/shops/{shop.slug}/").content.decode()

        assert "Ravi" in body
        assert "Priya" in body
        assert "Gone" not in body


class TestChangingTheAddress:
    def test_changing_it_breaks_the_old_address_cleanly(self, client):
        """Deliberately: a redirect would mean the shop can never start again
        on a name it has outgrown, because the old one would shadow it for
        good — and every leaflet ever printed would keep working forever."""
        shop = a_shop()
        make_service(shop)
        old = shop.slug

        shop.slug = "a-brand-new-name"
        shop.save()

        assert client.get(f"/shops/{old}/").status_code == 404
        assert client.get(f"/shops/{shop.slug}/").status_code == 200

    def test_the_new_address_works_immediately(self, client):
        shop = a_shop()
        shop.slug = "renamed"
        shop.save()
        make_service(shop)

        assert client.get("/shops/renamed/").status_code == 200
