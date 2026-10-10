"""Drop the pre-v1 tables.

Everything in them has been copied into ``providers``, ``accounts``, ``bookings``
and ``reviews``. They are now dead weight — and, on an instance that has been
running for years, quite a lot of it.

One migration drops all of them rather than each app dropping its own, because
the foreign keys run in every direction: ``haircut_appointments`` points at
``accounts_barberdetails``, which points at ``accounts_user``. ``CASCADE``
resolves the ordering, and ``IF EXISTS`` makes this safe to re-run.
"""

from django.db import migrations

TABLES = [
    # Dropped first; CASCADE removes the dependents' constraints.
    "haircut_appointments",
    "haircut_ratingsandreviews",
    "haircut_notificationtokens",
    "accounts_bankdetails",
    "accounts_barberdetails",
    "accounts_userdetails",
    "accounts_servicesdetails",
    "accounts_signupcodes",
    "accounts_passwordcodes",
    "accounts_emails",
]


def drop_legacy_tables(apps, schema_editor):
    for table in TABLES:
        schema_editor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


class Migration(migrations.Migration):
    dependencies = [
        ("bookings", "0002_migrate_legacy_bookings"),
        ("accounts", "0007_remove_legacy_profiles"),
    ]

    operations = [migrations.RunPython(drop_legacy_tables, migrations.RunPython.noop)]