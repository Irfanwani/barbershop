"""Aggregated pricing.

The numbers here are what a customer uses to decide where to go, so the tests
are about the ways an aggregate lies: averaging in a placeholder price, or
presenting two shops as if they were a trend.
"""

from __future__ import annotations

import pytest

from providers.models import ServiceType
from providers.pricing import (
    MAX_PLAUSIBLE_PRICE,
    MIN_PLAUSIBLE_PRICE,
    MIN_SAMPLE_FOR_CONFIDENCE,
    price_band,
    service_name_bands,
)
from tests.factories import make_profile, make_service

pytestmark = pytest.mark.django_db


def shop_with(*prices: int, service_type: str = ServiceType.BARBERSHOP, name: str = "Haircut"):
    provider = make_profile(service_type=service_type)
    for index, price in enumerate(prices):
        make_service(provider, name=f"{name} {index}", price=price)
    return provider


def band_for(prices, service_type=ServiceType.BARBERSHOP):
    shop_with(*prices, service_type=service_type)
    from providers.models import Service

    return price_band(
        service_type, "Barber shop", Service.objects.filter(provider__service_type=service_type)
    )


class TestBand:
    def test_an_empty_platform_has_no_median(self):
        from providers.models import Service

        band = price_band(ServiceType.BARBERSHOP, "Barber shop", Service.objects.none())

        assert band.sample_size == 0
        assert band.median is None
        assert band.is_thin is True

    def test_reports_the_range(self):
        band = band_for([20000, 30000, 40000])

        assert band.minimum == 20000
        assert band.maximum == 40000
        assert band.sample_size == 3

    def test_the_median_of_an_odd_count_is_the_middle_value(self):
        assert band_for([10000, 20000, 30000]).median == 20000

    def test_the_median_of_an_even_count_sits_between_the_two_middles(self):
        assert band_for([10000, 20000, 30000, 40000]).median == 25000

    def test_the_median_is_a_price_somebody_actually_charges(self):
        # Rounded down rather than averaged to 25001. A median of ₹250.005 is
        # not a price any shop has, and quoting it would be quoting fiction.
        assert band_for([10000, 40000, 10000, 40000]).median in (10000, 40000, 25000)

    def test_the_quartiles_bracket_the_median(self):
        band = band_for([10000, 20000, 30000, 40000, 50000])

        assert band.p25 is not None
        assert band.median is not None
        assert band.p75 is not None
        assert band.p25 <= band.median <= band.p75

    def test_a_single_shop_is_marked_thin(self):
        # A median of one shop is not a median, it is that shop's price.
        assert band_for([20000]).is_thin is True

    def test_three_shops_is_enough_to_stop_guessing(self):
        assert MIN_SAMPLE_FOR_CONFIDENCE == 3
        assert band_for([20000, 30000, 40000]).is_thin is False

    def test_prices_are_rendered_for_display(self):
        payload = band_for([20000, 30000, 40000]).as_dict()

        assert payload["median_display"] == "₹300.00"
        assert payload["minimum_display"] == "₹200.00"


class TestPlausibility:
    def test_a_placeholder_price_does_not_move_the_median(self):
        real = [20000, 30000, 40000]

        # A ₹0.01 haircut is a mistake, not a bargain. Averaging it in makes the
        # whole figure useless to anybody choosing where to go.
        assert band_for([*real, 1]).median == band_for(real).median

    def test_an_absurd_price_does_not_move_the_median(self):
        real = [20000, 30000, 40000]

        assert band_for([*real, MAX_PLAUSIBLE_PRICE + 1]).median == band_for(real).median

    def test_a_price_at_the_edge_of_the_band_still_counts(self):
        assert band_for([MIN_PLAUSIBLE_PRICE, 20000, 30000]).sample_size == 3

    def test_a_retired_service_is_not_counted(self):
        provider = shop_with(20000, 30000, 40000)
        provider.services.update(is_active=False)

        from providers.models import Service

        band = price_band(
            ServiceType.BARBERSHOP,
            "Barber shop",
            Service.objects.filter(provider__service_type=ServiceType.BARBERSHOP),
        )

        assert band.sample_size == 0


class TestByShopType:
    def test_each_shop_type_gets_its_own_figure(self):
        shop_with(20000, 30000, 40000, service_type=ServiceType.BARBERSHOP)
        shop_with(80000, 90000, 100000, service_type=ServiceType.SPA)

        from providers.models import Service

        barbers = price_band(
            ServiceType.BARBERSHOP,
            "Barber shop",
            Service.objects.filter(provider__service_type=ServiceType.BARBERSHOP),
        )
        spa = price_band(
            ServiceType.SPA, "Spa", Service.objects.filter(provider__service_type=ServiceType.SPA)
        )

        assert barbers.median == 30000
        assert spa.median == 90000


class TestServiceNameBands:
    def test_compares_a_name_several_shops_use(self):
        from providers.models import Service

        for price in (20000, 30000, 40000):
            make_service(make_profile(), name="Haircut", price=price)

        bands = service_name_bands(Service.objects.all())

        assert [band["name"] for band in bands] == ["Haircut"]
        assert bands[0]["median"] == 30000

    def test_ignores_a_name_only_one_shop_uses(self):
        from providers.models import Service

        make_service(make_profile(), name="Scalp massage ritual", price=90000)

        # "Scalp massage ritual" at one shop is not a typical price for it.
        assert service_name_bands(Service.objects.all()) == []

    def test_keeps_the_ordering_of_the_count(self):
        from providers.models import Service

        for _ in range(4):
            make_service(make_profile(), name="Beard trim", price=10000)
        for _ in range(3):
            make_service(make_profile(), name="Haircut", price=20000)

        bands = service_name_bands(Service.objects.all())

        assert [band["name"] for band in bands] == ["Beard trim", "Haircut"]

    def test_honours_the_limit(self):
        from providers.models import Service

        for index in range(8):
            for _ in range(3):
                make_service(make_profile(), name=f"Service {index}", price=20000)

        assert len(service_name_bands(Service.objects.all(), limit=3)) == 3
