"""Remove the legacy profile models from the project state.

``0006_migrate_legacy_profiles`` has already copied every row into
``providers``, ``accounts`` and ``payments``. These models are removed from
Django's view of the world here, but the **tables are left alone**: the
physical ``DROP TABLE`` happens in ``bookings/0003_drop_legacy_tables``, once
nothing points at them any more.

Why state-only: ``haircut_appointments`` still holds foreign keys into
``accounts_barberdetails``, and dropping the parent table first would either
fail or cascade away rows the booking migration has not read yet.
"""

from django.db import migrations

LEGACY_MODELS = [
    "BankDetails",
    "BarberDetails",
    "UserDetails",
    "ServicesDetails",
    "SignUpCodes",
    "PasswordCodes",
    "Emails",
]


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_migrate_legacy_profiles"),
        # Deliberately no dependency on the `haircut` app, which no longer
        # exists. It depended on these models in the other direction, and the
        # migration graph cannot outlive the app it points at. Ordering is
        # preserved where it matters: `accounts/0006` copies the profiles out
        # and `bookings/0002` copies the appointments out, both of which run
        # before anything is dropped.
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name=name) for name in LEGACY_MODELS]
        )
    ]