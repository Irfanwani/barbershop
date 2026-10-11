"""Tests for the demo seed command.

The seed is what every new contributor sees first, and what CI's smoke check
runs. If it produces a database the app cannot render, that is a bad first
hour for whoever is trying the project.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from accounts.models import CustomerProfile, Role, User
from bookings.models import Booking, BookingStatus
from providers.models import ProviderPayout, ProviderProfile, Service
from reviews.models import Review

pytestmark = pytest.mark.django_db(transaction=True)


def seed(**kwargs) -> None:
    call_command("seed_demo", **kwargs)


class TestSeed:
    def test_creates_providers_with_menus_and_payouts(self):
        seed(customers=4, bookings=5)

        assert ProviderProfile.objects.count() == 6
        assert Service.objects.count() > 0
        assert ProviderPayout.objects.count() == ProviderProfile.objects.count()

    def test_creates_verified_customers_with_locations(self):
        seed(customers=4, bookings=2)

        customers = User.objects.filter(role=Role.CUSTOMER)
        assert customers.count() == 4
        assert all(user.is_verified for user in customers)
        assert all(CustomerProfile.objects.get(user=user).coords is not None for user in customers)

    def test_demo_passwords_are_documented_and_work(self):
        """The seed prints these credentials; they had better actually work."""
        from django.contrib.auth import authenticate

        seed(customers=2, bookings=1)

        assert authenticate(username="provider1", password="Provider!123") is not None
        assert authenticate(username="customer1", password="Customer!123") is not None

    def test_bookings_are_priced_and_snapshotted(self):
        seed(customers=4, bookings=12)

        for booking in Booking.objects.all():
            assert booking.total == booking.subtotal + booking.platform_fee
            assert booking.items.exists()
            assert booking.items.first().unit_price > 0

    def test_the_seed_produces_bookings_at_any_hour(self, monkeypatch):
        """Regression: the seed used to depend on the time of day it ran.

        It built slots by adding an hour offset to *now*, so running it at
        14:00 put most candidates outside every shop's opening hours and it
        produced nothing at all. A demo that works only before lunchtime is not
        a demo.
        """
        from django.utils import timezone as dj_timezone

        late_evening = dj_timezone.now() + dj_timezone.timedelta(hours=9)
        monkeypatch.setattr(dj_timezone, "now", lambda: late_evening)
        # `now` is read once at the top of _create_bookings.
        monkeypatch.setattr("django.utils.timezone.now", lambda: late_evening, raising=True)

        seed(customers=6, bookings=40)

        assert Booking.objects.count() == 40

    def test_no_seeded_booking_runs_past_closing_time(self):
        from django.utils import timezone as dj_timezone

        seed(customers=6, bookings=40)

        for booking in Booking.objects.all():
            local_end = dj_timezone.localtime(booking.ends_at).time()
            assert local_end <= booking.provider.closing_time

    def test_recent_past_bookings_are_marked_finished(self):
        """Expired appointments are kept and tagged, not deleted."""
        seed(customers=6, bookings=40)

        past = Booking.objects.filter(starts_at__lt=timezone.now())
        assert past.exists(), "the seed should produce history"
        assert all(
            booking.status in {BookingStatus.COMPLETED, BookingStatus.NO_SHOW} for booking in past
        )

    def test_future_bookings_are_not_in_the_past_state(self):
        from django.utils import timezone

        seed(customers=6, bookings=40)

        future = Booking.objects.filter(starts_at__gte=timezone.now())
        assert all(
            booking.status in {BookingStatus.CONFIRMED, BookingStatus.PENDING_PAYMENT}
            for booking in future
        )

    def test_reviews_refresh_the_cached_provider_rating(self):
        seed(customers=4, bookings=1)

        for profile in ProviderProfile.objects.all():
            assert profile.rating_count == profile.reviews.count()
            if profile.rating_count:
                assert 1 <= float(profile.rating_average) <= 5

    def test_bookings_stay_inside_opening_hours(self):
        from django.utils import timezone

        seed(customers=4, bookings=20)

        for booking in Booking.objects.all():
            local = timezone.localtime(booking.starts_at)
            assert booking.provider.opening_time <= local.time()
            assert local.time() <= booking.provider.closing_time

    def test_refuses_to_seed_over_existing_providers(self):
        seed(customers=2, bookings=1)

        with pytest.raises(CommandError, match="already has providers"):
            seed()

    def test_force_overrides_that_guard(self):
        seed(customers=2, bookings=1)

        seed(customers=5, bookings=1, force=True)

        assert User.objects.filter(role=Role.CUSTOMER).count() == 5

    def test_seeding_twice_does_not_duplicate_the_demo_accounts(self):
        seed(customers=3, bookings=1)

        seed(customers=3, bookings=1, force=True)

        assert User.objects.filter(username__startswith="provider").count() == 6
        assert ProviderProfile.objects.count() == 6

    def test_is_reproducible(self):
        """Same seed, same data — so a bug reported against demo data reproduces.

        Booking times are relative to "now", so they cannot match to the
        microsecond across two runs. Everything that does not depend on the
        clock has to match exactly.
        """
        seed(customers=3, bookings=8)
        first = self._shape()

        for model in (
            Booking,
            Review,
            Service,
            ProviderPayout,
            ProviderProfile,
            CustomerProfile,
            User,
        ):
            model.objects.all().delete()

        seed(customers=3, bookings=8)
        second = self._shape()

        assert first == second

    @staticmethod
    def _shape() -> dict:
        return {
            "providers": sorted(
                ProviderProfile.objects.values_list(
                    "display_name", "service_type", "employee_count"
                )
            ),
            "services": sorted(Service.objects.values_list("name", "price")),
            "reviews": sorted(Review.objects.values_list("rating", "comment")),
            "ratings": sorted(ProviderProfile.objects.values_list("rating_average")),
            "prices": sorted(Booking.objects.values_list("subtotal", "platform_fee", "total")),
            "counts": (
                Booking.objects.count(),
                Review.objects.count(),
                Service.objects.count(),
            ),
        }
