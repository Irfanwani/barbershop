"""Tests for the pre-v1 -> v1 data migrations.

The migrations cannot be reversed — that is deliberate — so the migration graph
cannot be walked backwards to build a legacy database. Instead these tests
create the legacy tables with the exact column layout they had, populate them
with awkward but reachable data, and call the migration functions directly
against the real app registry.

The legacy data is deliberately messy, because in production it is:

* duplicate service names (the old schema allowed them, the new one does not)
* a 9-star rating (the old column had no range constraint)
* a price that already had the platform's 10% baked in at write time
* an appointment that expired months ago
* a bank account number in plaintext
* an account whose address was verified

If this migration has a bug, this is the only place it shows up before a
production deploy.
"""

from __future__ import annotations

import pytest
from django.contrib.gis.geos import Point
from django.db import connection
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)

# Verbatim from the pre-v1 schema. `id_id`, not `id`: these tables key off a
# OneToOneField whose primary key points at accounts_user.
LEGACY_DDL = [
    """
    CREATE TABLE accounts_userdetails (
        id_id bigint PRIMARY KEY, image varchar(100) NOT NULL DEFAULT '',
        coords geometry(POINT, 4326) NOT NULL, location varchar(1000) NOT NULL,
        about text NOT NULL, contact varchar(200) NOT NULL DEFAULT '')
    """,
    """
    CREATE TABLE accounts_barberdetails (
        id_id bigint PRIMARY KEY, image varchar(100) NOT NULL DEFAULT '',
        coords geometry(POINT, 4326) NOT NULL, location varchar(1000) NOT NULL,
        about text NOT NULL, contact varchar(200) NOT NULL DEFAULT '',
        employee_count integer NOT NULL, start_time time NOT NULL, end_time time NOT NULL,
        service_type varchar(60) NOT NULL)
    """,
    """
    CREATE TABLE accounts_servicesdetails (
        id bigserial PRIMARY KEY, service_provider_id bigint NOT NULL,
        service varchar(100) NOT NULL, cost integer NOT NULL)
    """,
    """
    CREATE TABLE accounts_bankdetails (
        id_id bigint PRIMARY KEY, business_name varchar(100) NOT NULL,
        business_type varchar(100) NOT NULL, beneficiary_name varchar(60) NOT NULL,
        account_number bigint NOT NULL, ifsc_code varchar(20) NOT NULL,
        account_type varchar(60), account_id varchar(60) NOT NULL,
        destination varchar(60) NOT NULL)
    """,
    "CREATE TABLE accounts_signupcodes (id bigserial PRIMARY KEY, user_id bigint NOT NULL, code varchar(15) NOT NULL)",
    "CREATE TABLE accounts_passwordcodes (id bigserial PRIMARY KEY, user_id bigint NOT NULL, code varchar(15) NOT NULL)",
    "CREATE TABLE accounts_emails (id bigserial PRIMARY KEY, user_id bigint NOT NULL, email varchar(254) NOT NULL)",
    """
    CREATE TABLE haircut_appointments (
        id bigserial PRIMARY KEY, datetime timestamptz NOT NULL, barber_id bigint NOT NULL,
        user_id bigint NOT NULL, "bookingID" integer NOT NULL,
        services varchar(1000) NOT NULL, totalcost integer NOT NULL, paid boolean NOT NULL)
    """,
    """
    CREATE TABLE haircut_ratingsandreviews (
        id bigserial PRIMARY KEY, ratings integer NOT NULL, comments varchar(1000),
        barber_id bigint NOT NULL, user_id bigint NOT NULL, date date NOT NULL)
    """,
    "CREATE TABLE haircut_notificationtokens (id bigserial PRIMARY KEY, token varchar(200) NOT NULL, user_id bigint NOT NULL)",
]

# Reverse order: dependents first.
DROP_DDL = [
    "DROP TABLE IF EXISTS accounts_signupcodes",
    "DROP TABLE IF EXISTS accounts_passwordcodes",
    "DROP TABLE IF EXISTS accounts_emails",
    "DROP TABLE IF EXISTS accounts_userdetails",
    "DROP TABLE IF EXISTS accounts_barberdetails",
    "DROP TABLE IF EXISTS accounts_servicesdetails",
    "DROP TABLE IF EXISTS accounts_bankdetails",
    "DROP TABLE IF EXISTS haircut_appointments",
    "DROP TABLE IF EXISTS haircut_ratingsandreviews",
    "DROP TABLE IF EXISTS haircut_notificationtokens",
]


class SchemaEditor:
    """The slice of Django's schema editor that a RunPython body actually uses."""

    def __init__(self):
        self.connection = connection

    def execute(self, sql, params=None):
        with connection.cursor() as cursor:
            cursor.execute(sql, params)


@pytest.fixture
def legacy_database():
    """Create the legacy tables, then remove them again afterwards."""
    with connection.schema_editor(atomic=False) as editor:
        for ddl in LEGACY_DDL:
            editor.execute(ddl)
    try:
        yield SchemaEditor()
    finally:
        with connection.schema_editor(atomic=False) as editor:
            for ddl in DROP_DDL:
                editor.execute(ddl)


@pytest.fixture
def seeded_legacy(legacy_database):
    """Legacy rows that exercise every branch of the migrations."""
    from tests.factories import make_provider_user, make_user

    # Unverified, because the legacy schema tracked verification separately and
    # these four accounts were not in that table.
    customer = make_user("legacy_customer", email="cust@example.com", verified=False)
    provider_user = make_provider_user("legacy_provider", email="prov@example.com", verified=False)
    reviewer = make_user("legacy_reviewer", email="rev@example.com", verified=False)
    verified = make_user("legacy_verified", email="verified@example.com", verified=False)

    cursor = legacy_database.connection.cursor()

    cursor.execute(
        "INSERT INTO accounts_userdetails VALUES (%s, '', %s, %s, %s, %s)",
        [
            customer.id,
            "SRID=4326;POINT(77.2090 28.6139)",
            "Connaught Place",
            "Prefers afternoons",
            "+911234567890",
        ],
    )
    cursor.execute(
        "INSERT INTO accounts_barberdetails VALUES (%s, '', %s, %s, %s, %s, %s, %s, %s, %s)",
        [
            provider_user.id,
            "SRID=4326;POINT(77.2110 28.6150)",
            "Sector 5",
            "Ten years on the chair",
            "+919999999999",
            3,
            "09:00:00",
            "20:00:00",
            "barbershop",
        ],
    )
    # Duplicate names: the old schema allowed them.
    cursor.execute(
        "INSERT INTO accounts_servicesdetails (service_provider_id, service, cost) VALUES (%s, 'Haircut', 300)",
        [provider_user.id],
    )
    cursor.execute(
        "INSERT INTO accounts_servicesdetails (service_provider_id, service, cost) VALUES (%s, 'Haircut', 500)",
        [provider_user.id],
    )
    cursor.execute(
        "INSERT INTO accounts_servicesdetails (service_provider_id, service, cost) VALUES (%s, 'Beard trim', 110)",
        [provider_user.id],
    )

    cursor.execute(
        "INSERT INTO accounts_bankdetails VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [
            provider_user.id,
            "Sharp Cuts",
            "proprietorship",
            "Irfan Wani",
            4111111111111111,
            "HDFC0001234",
            "savings",
            "fa_123",
            "IRFAN@HDFC",
        ],
    )
    cursor.execute(
        "INSERT INTO accounts_emails (user_id, email) VALUES (%s, %s)",
        [verified.id, verified.email],
    )
    cursor.execute(
        "INSERT INTO accounts_signupcodes (user_id, code) VALUES (%s, 'LEGACYCODE')", [customer.id]
    )
    cursor.execute(
        "INSERT INTO accounts_passwordcodes (user_id, code) VALUES (%s, 'LEGACYRESET')",
        [customer.id],
    )

    now = timezone.now()
    cursor.execute(
        'INSERT INTO haircut_appointments (datetime, barber_id, user_id, "bookingID", services, totalcost, paid) '
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        [
            now + timezone.timedelta(days=2),
            provider_user.id,
            customer.id,
            1001,
            "Haircut|Beard trim",
            440,
            True,
        ],
    )
    cursor.execute(
        'INSERT INTO haircut_appointments (datetime, barber_id, user_id, "bookingID", services, totalcost, paid) '
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        [
            now - timezone.timedelta(days=9),
            provider_user.id,
            customer.id,
            1002,
            "Haircut",
            275,
            False,
        ],
    )
    cursor.execute(
        "INSERT INTO haircut_ratingsandreviews (ratings, comments, barber_id, user_id, date) "
        "VALUES (5, 'Excellent', %s, %s, %s)",
        [provider_user.id, reviewer.id, now.date()],
    )
    # The old column had no range constraint, so a 9 is reachable.
    cursor.execute(
        "INSERT INTO haircut_ratingsandreviews (ratings, comments, barber_id, user_id, date) "
        "VALUES (9, 'Wild', %s, %s, %s)",
        [provider_user.id, reviewer.id, now.date()],
    )
    cursor.execute(
        "INSERT INTO haircut_notificationtokens (token, user_id) VALUES (%s, %s)",
        ["ExponentPushToken[legacy]", customer.id],
    )

    yield {
        "customer": customer,
        "provider_user": provider_user,
        "reviewer": reviewer,
        "verified": verified,
    }


@pytest.fixture
def migrated(seeded_legacy, legacy_database):
    from importlib import import_module

    from django.apps import apps as live_apps

    # Migration modules start with a digit, so they can only be reached through
    # importlib rather than an `import` statement.
    profiles_migration = import_module("accounts.migrations.0006_migrate_legacy_profiles")
    bookings_migration = import_module("bookings.migrations.0002_migrate_legacy_bookings")

    profiles_migration.forward(live_apps, legacy_database)
    bookings_migration.forward(live_apps, legacy_database)
    return seeded_legacy


# ---------------------------------------------------------------------------
# profiles
# ---------------------------------------------------------------------------


class TestProfileMigration:
    def test_customer_profile_is_created(self, migrated):
        from accounts.models import CustomerProfile

        profile = CustomerProfile.objects.get(user=migrated["customer"])

        assert profile.address == "Connaught Place"
        assert profile.about == "Prefers afternoons"

    def test_coordinates_become_geography_on_a_spheroid(self, migrated):
        from accounts.models import CustomerProfile

        profile = CustomerProfile.objects.get(user=migrated["customer"])

        assert profile.coords.srid == 4326
        assert abs(profile.coords.y - 28.6139) < 1e-6
        assert abs(profile.coords.x - 77.2090) < 1e-6

    def test_provider_profile_is_created(self, migrated):
        from providers.models import ProviderProfile

        profile = ProviderProfile.objects.get(user=migrated["provider_user"])

        assert profile.address == "Sector 5"
        assert profile.employee_count == 3
        assert profile.service_type == "barbershop"
        assert profile.description == "Ten years on the chair"

    def test_roles_are_set_explicitly(self, migrated):
        migrated["provider_user"].refresh_from_db()
        migrated["customer"].refresh_from_db()

        assert migrated["provider_user"].role == "provider"
        assert migrated["customer"].role == "customer"

    def test_verification_is_carried_over(self, migrated):
        migrated["verified"].refresh_from_db()
        migrated["customer"].refresh_from_db()

        assert migrated["verified"].is_verified is True
        assert migrated["customer"].is_verified is False

    def test_prices_have_the_old_commission_stripped(self, migrated):
        from providers.models import ProviderProfile, Service

        profile = ProviderProfile.objects.get(user=migrated["provider_user"])
        haircut = Service.objects.get(provider=profile, name="Haircut")

        # Stored at 300, which already included the platform's 10%.
        assert haircut.price == 273

    def test_duplicate_service_names_collapse_to_one(self, migrated):
        from providers.models import ProviderProfile, Service

        profile = ProviderProfile.objects.get(user=migrated["provider_user"])

        assert Service.objects.filter(provider=profile, name="Haircut").count() == 1
        assert Service.objects.filter(provider=profile).count() == 2

    def test_payout_is_migrated(self, migrated):
        from providers.models import ProviderPayout, ProviderProfile

        profile = ProviderProfile.objects.get(user=migrated["provider_user"])
        payout = ProviderPayout.objects.get(provider=profile)

        assert payout.business_name == "Sharp Cuts"
        assert payout.account_number == "4111111111111111"
        assert payout.ifsc_code == "HDFC0001234"
        assert payout.razorpay_account_id == "fa_123"

    def test_the_account_number_is_encrypted_at_rest(self, migrated):

        with connection.cursor() as cursor:
            cursor.execute("SELECT account_number FROM providers_payout")
            raw = cursor.fetchall()

        assert all(row[0].startswith("gAAAA") for row in raw)
        assert all("4111111111111111" not in row[0] for row in raw)

    def test_the_masked_number_is_all_the_client_ever_gets(self, migrated):
        from providers.models import ProviderPayout

        payout = ProviderPayout.objects.get()

        assert payout.account_number_masked == "•" * 12 + "1111"

    def test_obsolete_plaintext_codes_are_cleared(self, migrated):
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM accounts_signupcodes")
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT count(*) FROM accounts_passwordcodes")
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT count(*) FROM accounts_emails")
            assert cursor.fetchone()[0] == 0


# ---------------------------------------------------------------------------
# bookings
# ---------------------------------------------------------------------------


class TestBookingMigration:
    def test_both_appointments_survive(self, migrated):
        from bookings.models import Booking

        assert Booking.objects.count() == 2

    def test_an_expired_appointment_is_kept_not_deleted(self, migrated):
        from bookings.models import Booking

        expired = Booking.objects.get(status="no_show")

        assert expired.starts_at < timezone.now()
        assert expired.minutes_until_start() < 0

    def test_the_pipe_delimited_services_become_line_items(self, migrated):
        from bookings.models import Booking

        booking = Booking.objects.get(status="confirmed")

        assert booking.items.count() == 2
        assert set(booking.items.values_list("name", flat=True)) == {"Haircut", "Beard trim"}

    def test_line_items_link_to_the_live_menu(self, migrated):
        from bookings.models import Booking

        booking = Booking.objects.get(status="confirmed")
        linked = [item for item in booking.items.all() if item.service_id]

        assert linked, "services still on the menu should be linked"

    def test_a_deleted_service_leaves_the_snapshot_intact(self, migrated):
        """Deleting a menu item must not erase it from past invoices."""
        from bookings.models import Booking
        from providers.models import Service

        booking = Booking.objects.get(status="confirmed")
        item = booking.items.exclude(service_id=None).first()
        Service.objects.filter(pk=item.service_id).delete()

        item.refresh_from_db()

        assert item.service_id is None
        assert item.name  # the snapshot survives
        assert item.unit_price > 0

    def test_the_total_is_decomposed_into_subtotal_and_fee(self, migrated):
        from bookings.models import Booking

        booking = Booking.objects.get(status="confirmed")

        assert booking.total == 440
        assert booking.subtotal + booking.platform_fee == booking.total
        assert booking.subtotal == 400

    def test_references_are_generated_and_unique(self, migrated):
        from bookings.models import Booking

        references = list(Booking.objects.values_list("reference", flat=True))

        assert all(ref.startswith("BK-") for ref in references)
        assert len(set(references)) == len(references)

    def test_reference_generation_is_deterministic(self):
        """The same legacy row must always produce the same customer-facing code.

        Not cosmetic: a re-run of the migration has to land on the codes already
        handed out, not mint a second set.
        """
        from importlib import import_module

        migration = import_module("bookings.migrations.0002_migrate_legacy_bookings")

        first = migration._reference(1001, 7)
        second = migration._reference(1001, 7)
        other = migration._reference(1002, 8)

        assert first == second
        assert first != other
        assert first.startswith("BK-")

    def test_reference_uses_an_unambiguous_alphabet(self):
        from importlib import import_module

        migration = import_module("bookings.migrations.0002_migrate_legacy_bookings")

        codes = {migration._reference(row_id, row_id) for row_id in range(500)}

        assert len(codes) == 500, "references must not collide"
        assert not set("IO01") & set("".join(codes))

    def test_the_provider_is_mapped_through_the_user_id(self, migrated):
        from bookings.models import Booking
        from providers.models import ProviderProfile

        booking = Booking.objects.get(status="confirmed")
        profile = ProviderProfile.objects.get(user=migrated["provider_user"])

        assert booking.provider_id == profile.id

    def test_the_customer_is_mapped_through_the_user_id(self, migrated):
        from bookings.models import Booking

        assert Booking.objects.get(status="confirmed").customer_id == migrated["customer"].id

    def test_ratings_are_migrated_and_clamped_into_range(self, migrated):
        from reviews.models import Review

        assert sorted(Review.objects.values_list("rating", flat=True)) == [5, 5]

    def test_push_tokens_are_migrated(self, migrated):
        from accounts.models import PushToken

        assert PushToken.objects.get().token == "ExponentPushToken[legacy]"

    def test_the_provider_rating_cache_is_recalculated(self, migrated):
        from providers.models import ProviderProfile

        profile = ProviderProfile.objects.get(user=migrated["provider_user"])

        assert profile.rating_count == 2
        assert float(profile.rating_average) == 5.0


# ---------------------------------------------------------------------------
# reversibility
# ---------------------------------------------------------------------------


def test_the_profile_migration_refuses_to_reverse(legacy_database):
    from importlib import import_module

    from django.apps import apps as live_apps

    migration = import_module("accounts.migrations.0006_migrate_legacy_profiles")

    with pytest.raises(NotImplementedError, match="not reversible"):
        migration.reverse(live_apps, legacy_database)


def test_the_booking_migration_refuses_to_reverse(legacy_database):
    from importlib import import_module

    from django.apps import apps as live_apps

    migration = import_module("bookings.migrations.0002_migrate_legacy_bookings")

    with pytest.raises(NotImplementedError, match="not reversible"):
        migration.reverse(live_apps, legacy_database)


def test_a_migrated_booking_satisfies_the_new_constraints(migrated):
    """The point of the exercise: the result is valid under the new schema."""
    from bookings.models import Booking

    for booking in Booking.objects.all():
        booking.full_clean(exclude=["customer", "provider"])


def test_point_helpers_stay_consistent(migrated):
    """Sanity check that the converted coordinates are still points, not garbage."""
    from providers.models import ProviderProfile

    profile = ProviderProfile.objects.get()

    assert isinstance(profile.coords, Point)
    assert profile.coords.srid == 4326
