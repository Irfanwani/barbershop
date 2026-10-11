"""Naming a barber rather than a shop.

``employee_count`` was an integer, so a shop with four barbers was "capacity 4"
and no booking could ever name one of them. "Can I book with Ravi?" is the
first thing a customer asks and every competitor answers it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import time, timedelta

import pytest
from django.contrib.auth.models import AbstractBaseUser
from django.test import Client
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from providers.models import ProviderProfile, Service, Staff, StaffWorkingHours
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

#: The shop is open every Monday, whatever day the suite happens to run on.
MONDAY = 0


@dataclass
class Shop:
    """A shop with named staff and one bookable service."""

    owner: AbstractBaseUser
    profile: ProviderProfile
    staff: list[Staff]
    service: Service
    token: str

    def person(self, index: int) -> Staff:
        return self.staff[index]


def build_shop(count: int = 2, employee_count: int | None = None) -> Shop:
    owner = make_provider_user(f"owner{count}{employee_count or ''}")
    _client, token = logged_in(owner)
    profile = make_profile(owner, display_name="Sharp Cuts Studio")
    if employee_count is not None:
        # Set directly rather than through the factory's kwargs, which are
        # typed against the parameters it actually declares.
        profile.employee_count = employee_count
        profile.save(update_fields=["employee_count"])
    staff = [
        Staff.objects.create(provider=profile, name=f"Barber {i}") for i in range(1, count + 1)
    ]
    service = make_service(profile, price=20000, duration_minutes=40)
    return Shop(owner=owner, profile=profile, staff=staff, service=service, token=token)


@dataclass
class Session:
    """A signed-in user: the client that makes requests, and its token."""

    client: Client
    token: str

    def auth(self) -> dict:
        return auth_header(self.token)


@pytest.fixture
def customer() -> Session:
    """A signed-in customer.

    The booking has to be made by a *customer*: the shop owner cannot book
    themselves in, and posting with the owner's token tests something else.
    """
    client, token = logged_in(make_user("customer"))
    return Session(client=client, token=token)


@pytest.fixture
def shop():
    return build_shop(2)


def book(who: Session, shop: Shop, starts_at, *, staff=None):
    """Book this shop's service, optionally naming who does it."""
    payload: dict = {
        "provider": shop.profile.pk,
        "services": [shop.service.pk],
        "starts_at": starts_at.isoformat(),
    }
    if staff is not None:
        payload["staff"] = staff.pk
    return who.client.post(f"{V1}/bookings/new/", payload, **who.auth())


def two_days_from_now(hour: int = 10):
    day = timezone.localtime() + timedelta(days=2)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0)


def next_weekday(weekday: int, hour: int = 10):
    """A future instant falling on the given weekday (0 = Monday)."""
    now = timezone.localtime()
    days = (weekday - now.weekday()) % 7 or 7
    return (now + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)


class TestCapacity:
    def test_capacity_comes_from_the_staff_rows(self, shop):
        assert shop.profile.headcount() == 2

    def test_an_inactive_member_stops_counting(self, shop):
        shop.person(0).is_active = False
        shop.person(0).save()
        assert shop.profile.headcount() == 1

    def test_a_shop_with_no_staff_keeps_its_old_headcount(self):
        """A shop that has not set staff up must not lose its capacity.

        The rows win as soon as any exist; until then the integer it always had
        still applies, so the feature is opt-in rather than a migration that
        quietly closes half the shops.
        """
        shop = build_shop(0, employee_count=4)
        assert shop.profile.headcount() == 4

    def test_two_barbers_run_two_simultaneous_bookings(self, customer, shop):
        starts_at = two_days_from_now()

        for person in shop.staff:
            assert book(customer, shop, starts_at, staff=person).status_code == 201

        assert (
            Booking.objects.filter(
                provider=shop.profile, status=BookingStatus.PENDING_PAYMENT
            ).count()
            == 2
        )

    def test_a_third_booking_is_refused_when_only_two_work(self, customer, shop):
        starts_at = two_days_from_now()

        for person in shop.staff:
            book(customer, shop, starts_at, staff=person)

        before = Booking.objects.count()
        response = book(customer, shop, starts_at)
        assert response.status_code >= 400
        assert Booking.objects.count() == before


class TestOnePersonCannotBeTwoPlaces:
    def test_a_named_barber_cannot_be_booked_twice_at_once(self, customer, shop):
        """The shop having a free chair is not enough if it is their chair."""
        starts_at = two_days_from_now()

        assert book(customer, shop, starts_at, staff=shop.person(0)).status_code == 201

        response = book(customer, shop, starts_at, staff=shop.person(0))
        assert response.status_code >= 400
        assert "already taken" in str(response.data).lower()

    def test_the_other_barber_is_still_free_at_the_same_time(self, customer, shop):
        starts_at = two_days_from_now()

        book(customer, shop, starts_at, staff=shop.person(0))
        assert book(customer, shop, starts_at, staff=shop.person(1)).status_code == 201

    def test_an_unnamed_booking_does_not_double_book_a_person(self, customer, shop):
        """An unnamed booking takes whoever is free, which is what it always did."""
        starts_at = two_days_from_now()

        assert book(customer, shop, starts_at).status_code == 201
        assert book(customer, shop, starts_at).status_code == 201


class TestChoosingSomeoneClosed:
    def test_a_person_who_does_not_work_that_day_is_refused(self, customer, shop):
        StaffWorkingHours.objects.create(staff=shop.person(0), weekday=6, is_closed=True)

        response = book(customer, shop, next_weekday(6), staff=shop.person(0))
        assert response.status_code >= 400
        assert "does not work" in str(response.data).lower()

    def test_the_other_person_who_does_work_is_fine(self, customer, shop):
        StaffWorkingHours.objects.create(staff=shop.person(0), weekday=6, is_closed=True)
        StaffWorkingHours.objects.create(
            staff=shop.person(1),
            weekday=6,
            is_closed=False,
            opens_at=time(9, 0),
            closes_at=time(20, 0),
        )

        assert book(customer, shop, next_weekday(6), staff=shop.person(1)).status_code == 201

    def test_their_own_hours_narrow_the_window(self, customer, shop):
        StaffWorkingHours.objects.create(
            staff=shop.person(0),
            weekday=MONDAY,
            is_closed=False,
            opens_at=time(16, 0),
            closes_at=time(20, 0),
        )

        response = book(customer, shop, next_weekday(MONDAY, hour=10), staff=shop.person(0))
        assert response.status_code >= 400
        assert "16:00" in str(response.data)

    def test_having_no_hours_of_their_own_means_following_the_shop(self, customer, shop):
        # No StaffWorkingHours row at all, so they follow the shop — and Monday
        # is a day the shop is open on, so the booking is allowed.
        response = book(customer, shop, next_weekday(MONDAY, hour=11), staff=shop.person(0))
        assert response.status_code == 201, response.data


class TestValidation:
    def test_staff_from_another_shop_is_refused(self, customer, shop):
        """Otherwise the endpoint confirms which shops someone works for."""
        other = build_shop(1)
        starts_at = two_days_from_now()

        assert book(customer, shop, starts_at, staff=shop.person(0)).status_code == 201

        response = book(customer, shop, starts_at, staff=other.person(0))
        assert response.status_code >= 400
        assert "not available at this shop" in str(response.data)

    def test_an_inactive_member_cannot_be_booked(self, customer, shop):
        shop.person(0).is_active = False
        shop.person(0).save()

        response = book(customer, shop, two_days_from_now(), staff=shop.person(0))
        assert response.status_code >= 400

    def test_the_booking_records_who_is_doing_the_job(self, customer, shop):
        book(customer, shop, two_days_from_now(), staff=shop.person(0))

        booking = Booking.objects.get(provider=shop.profile)
        assert booking.staff_id == shop.person(0).pk

    def test_a_shop_with_named_staff_still_takes_unnamed_bookings(self, customer, shop):
        assert book(customer, shop, two_days_from_now()).status_code == 201
        assert Booking.objects.get(provider=shop.profile).staff_id is None


class TestEndpoints:
    def test_anyone_can_read_a_shops_public_staff(self, shop):
        reader = Session(*logged_in(make_user("reader")))

        response = reader.client.get(f"{V1}/providers/{shop.profile.pk}/staff/")
        assert response.status_code == 200
        assert {row["name"] for row in response.data} == {"Barber 1", "Barber 2"}

    def test_a_shopper_does_not_see_someone_who_left(self, shop):
        shop.person(0).is_active = False
        shop.person(0).save()
        reader = Session(*logged_in(make_user("reader2")))

        response = reader.client.get(f"{V1}/providers/{shop.profile.pk}/staff/")
        assert [row["name"] for row in response.data] == ["Barber 2"]

    def test_a_provider_can_add_someone(self, shop):
        owner = Session(*logged_in(shop.owner))

        response = owner.client.post(
            f"{V1}/providers/me/staff/",
            {"name": "Ravi", "bio": "Ten years cutting hair."},
            **owner.auth(),
        )
        assert response.status_code == 201, response.data
        assert response.data["name"] == "Ravi"
        assert shop.profile.headcount() == 3

    def test_adding_someone_takes_effect_on_capacity(self, shop):
        assert shop.profile.headcount() == 2
        owner = Session(*logged_in(shop.owner))

        owner.client.post(f"{V1}/providers/me/staff/", {"name": "Ravi"}, **owner.auth())
        assert shop.profile.headcount() == 3

    def test_a_provider_only_sees_their_own(self, shop):
        build_shop(1)
        owner = Session(*logged_in(shop.owner))

        response = owner.client.get(f"{V1}/providers/me/staff/", **owner.auth())
        assert response.status_code == 200, response.data
        assert [row["name"] for row in response.data] == ["Barber 1", "Barber 2"]

    def test_another_provider_cannot_edit_your_staff(self, shop):
        other = build_shop(1)
        intruder = Session(*logged_in(other.owner))

        response = intruder.client.patch(
            f"{V1}/providers/me/staff/{shop.person(0).pk}/",
            json.dumps({"name": "Hijacked"}),
            content_type="application/json",
            **intruder.auth(),
        )
        assert response.status_code == 404

    def test_retiring_someone_keeps_their_past_bookings(self, customer, shop):
        """A customer given a haircut by Ravi in March should see it in July."""
        book(customer, shop, two_days_from_now(), staff=shop.person(0))
        owner = Session(*logged_in(shop.owner))

        response = owner.client.delete(
            f"{V1}/providers/me/staff/{shop.person(0).pk}/", **owner.auth()
        )
        assert response.status_code == 204

        assert Staff.objects.filter(pk=shop.person(0).pk, is_active=False).exists()
        assert Booking.objects.get(provider=shop.profile).staff_id == shop.person(0).pk
        assert shop.profile.headcount() == 1

    def test_a_blank_name_is_refused(self, shop):
        owner = Session(*logged_in(shop.owner))

        response = owner.client.post(f"{V1}/providers/me/staff/", {"name": "   "}, **owner.auth())
        assert response.status_code == 400

    def test_two_people_cannot_share_a_name_at_one_shop(self, shop):
        owner = Session(*logged_in(shop.owner))
        owner.client.post(f"{V1}/providers/me/staff/", {"name": "Ravi"}, **owner.auth())

        response = owner.client.post(f"{V1}/providers/me/staff/", {"name": "Ravi"}, **owner.auth())
        assert response.status_code == 409

    def test_hours_can_be_set_with_the_person(self, shop):
        owner = Session(*logged_in(shop.owner))

        # JSON, not a form: nested lists cannot be expressed in multipart, and
        # a client that sends hours as form fields would silently lose them.
        response = owner.client.post(
            f"{V1}/providers/me/staff/",
            json.dumps(
                {
                    "name": "Ravi",
                    "hours": [
                        {"weekday": 6, "is_closed": True},
                        {
                            "weekday": 5,
                            "is_closed": False,
                            "opens_at": "10:00",
                            "closes_at": "16:00",
                        },
                    ],
                }
            ),
            content_type="application/json",
            **owner.auth(),
        )
        assert response.status_code == 201, response.data
        assert [row["weekday"] for row in response.data["hours"]] == [5, 6]


def _minimum_valid_row(model, **overrides) -> dict:
    """The fewest fields that satisfy NOT NULL on a historical model.

    The state being rebuilt is old, so the columns it expects are not the ones
    the current model has. Filling in whatever that state actually requires
    keeps the test about the migration rather than about which fields the
    accounts table happened to gain.
    """
    values = dict(overrides)
    for field in model._meta.concrete_fields:
        if field.name in values or field.has_default() or field.null or field.primary_key:
            continue
        values[field.name] = _placeholder_for(field)
    return values


def _placeholder_for(field):
    internal = field.get_internal_type()
    if internal in {"BooleanField"}:
        return True
    if internal in {"PositiveIntegerField", "PositiveSmallIntegerField", "IntegerField"}:
        return 1
    if internal in {"DateTimeField"}:
        return timezone.now()
    return "legacy"


class TestTheMigration:
    def test_the_data_migration_carries_headcount_over(self):
        """A shop with four barbers must not drop to one when this ships.

        Calls the migration function with the real app registry, which is what
        Django hands it at runtime. Unapplying and re-applying would test the
        wiring more directly, but it also means rebuilding the accounts table
        from a state that predates its columns — and the failure would then be
        about that rather than about the migration.
        """
        import importlib

        from django.apps import apps as real_apps

        module = importlib.import_module(
            "providers.migrations.0007_staff_staffworkinghours_and_more"
        )

        legacy = build_shop(0, employee_count=4)
        assert legacy.profile.staff.count() == 0

        module.carry_headcount_over(real_apps, None)

        rows = list(Staff.objects.filter(provider=legacy.profile))
        assert len(rows) == 4
        # Not invented names. A fabricated "Ravi" in a booking a customer can
        # see is worse than an unnamed one.
        assert all(row.is_placeholder for row in rows)
        assert all(row.name.startswith("Staff member") for row in rows)

    def test_a_shop_of_one_needs_no_placeholder(self):
        import importlib

        from django.apps import apps as real_apps

        module = importlib.import_module(
            "providers.migrations.0007_staff_staffworkinghours_and_more"
        )

        shop = build_shop(0, employee_count=1)
        module.carry_headcount_over(real_apps, None)

        # employee_count 1 is the default: inventing a placeholder for a
        # one-person shop would make every existing shop show a prompt.
        assert Staff.objects.filter(provider=shop.profile).count() == 0
