"""The public page for a shop.

This is the acquisition channel for an independent. A shop owner pastes this
address into an Instagram bio, a WhatsApp status, a printed leaflet. It has
to work on a phone with no app installed, on a slow connection, and when it
is previewed in a chat.

Which means it is rendered by the server, not by the app and not by the
single-page site: a link somebody is excited about should not depend on
JavaScript arriving first.
"""

from __future__ import annotations

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from providers.models import ProviderProfile


def site_url() -> str:
    return str(settings.PUBLIC_SITE_URL or "").rstrip("/")


def app_link(provider: ProviderProfile, *, path: str = "") -> str:
    """A link into the app, falling back to the website when it is absent.

    Deep links silently do nothing on a phone with no app, so a link that is
    only an app link reaches nobody on a shared computer or a work laptop.
    """
    target = f"barbershop://shop/{provider.slug}"
    if path:
        target = f"{target}/{path}"
    return f"https://barbershop.app/open?url={target}"


@require_GET
@cache_control(max_age=300, public=True)
def shop_page(request, slug: str) -> HttpResponse:
    """One shop, its menu and prices, and a way to book it.

    A 404 for an unknown slug, rather than a redirect to the listing. A shop
    that has changed its address should have its old link stop working
    cleanly; carrying every address forever would mean the shop can never
    start again on a name it has outgrown, because the old one would shadow
    it for good.
    """
    try:
        provider = ProviderProfile.objects.get(slug=slug)
    except ProviderProfile.DoesNotExist as exc:
        raise Http404("No shop at this address.") from exc

    services = list(
        provider.services.filter(is_active=True).select_related("provider").order_by("price")
    )
    staff = list(provider.staff.filter(is_active=True))
    lowest = min((service.price for service in services), default=None)

    context = {
        "provider": provider,
        "services": services,
        "staff": staff,
        "lowest_display": _rupees(lowest),
        "is_paused": not provider.is_bookable,
        "app_url": app_link(provider),
        "site_url": site_url(),
        "reviews": provider.reviews.select_related("customer").order_by("-created_at")[:5],
    }
    return render(request, "shops/public.html", context)


def _rupees(paise: int | None) -> str:
    return f"₹{paise / 100:.0f}" if paise else "—"
