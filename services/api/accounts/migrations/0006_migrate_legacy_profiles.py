"""Carry the pre-v1 profile data into the new models.

The old schema split one concept across four tables and inferred everything
else. ``UserDetails`` and ``BarberDetails`` both held a photo, coordinates, an
address and a description; which one a user had was the only thing that
distinguished a customer from a shop. ``ServicesDetails`` held a price that had
already had the platform's 10% added to it at write time. ``BankDetails`` held
an account number in plaintext.

Mapping:

============================  ==================================
old                           new
============================  ==================================
``UserDetails``               ``CustomerProfile`` (+ ``role``)
``BarberDetails``             ``ProviderProfile`` (+ ``role``)
``ServicesDetails.cost``      ``Service.price`` (fee stripped out)
``BankDetails``               ``ProviderPayout`` (encrypted)
``Emails``                    ``User.is_verified``
``SignUpCodes``/``Password``  nothing — superseded by VerificationCode
============================  ==================================

Coordinates are converted from ``geometry`` to ``geography``: the old column was
a flat plane, and ``ST_Distance`` over one understates real distance enough to
matter. Reversible; the reverse function is :func:`reverse_code`.
"""

from __future__ import annotations

from django.db import migrations

# The old view added 10% to every price as it stored it (and then again when
# reading a booking's total). Strip it so ``Service.price`` is the provider's
# own price, which is what the new pricing code assumes.
OLD_COMMISSION = 0.10


def _strip_commission(amount: int) -> int:
    return max(1, round(amount / (1 + OLD_COMMISSION)))


def forward(apps, schema_editor):
    CustomerProfile = apps.get_model("accounts", "CustomerProfile")
    ProviderProfile = apps.get_model("providers", "ProviderProfile")
    Service = apps.get_model("providers", "Service")
    ProviderPayout = apps.get_model("providers", "ProviderPayout")
    User = apps.get_model("accounts", "User")

    # --- customers -----------------------------------------------------------
    # `coords` is a raw SQL select rather than the historical model because the
    # column changes type: geometry in, geography out.
    CustomerProfile.objects.using(schema_editor.connection.alias).bulk_create(
        [
            CustomerProfile(
                user_id=row["id"],
                photo=row["image"] or None,
                about=row["about"] or "",
                address=row["location"] or "",
                coords=row["coords"],
                created_at=timezone_now(),
                updated_at=timezone_now(),
            )
            for row in _legacy_profiles(schema_editor, "accounts_userdetails")
        ],
        batch_size=500,
    )

    # --- providers -----------------------------------------------------------
    providers = [
        ProviderProfile(
            user_id=row["id"],
            display_name=row["display_name"],
            description=row["about"] or "",
            service_type=_clean_service_type(row["service_type"]),
            photo=row["image"] or None,
            address=row["location"] or "",
            coords=row["coords"],
            contact_phone=row["contact"] or "",
            employee_count=max(row["employee_count"] or 1, 1),
            opening_time=row["start_time"],
            closing_time=row["end_time"],
            slot_interval_minutes=30,
            is_accepting_bookings=True,
            requires_approval=False,
            created_at=timezone_now(),
            updated_at=timezone_now(),
        )
        for row in _legacy_profiles(schema_editor, "accounts_barberdetails")
    ]
    ProviderProfile.objects.using(schema_editor.connection.alias).bulk_create(
        providers, batch_size=500
    )

    # --- roles ---------------------------------------------------------------
    # Set explicitly rather than inferred, so `role` and "a profile exists"
    # cannot disagree the way the old `is_barber` flag did.
    User.objects.using(schema_editor.connection.alias).filter(
        id__in=ProviderProfile.objects.using(schema_editor.connection.alias).values("user_id")
    ).update(role="provider")
    User.objects.using(schema_editor.connection.alias).filter(
        id__in=CustomerProfile.objects.using(schema_editor.connection.alias).values("user_id")
    ).update(role="customer")

    # --- verification --------------------------------------------------------
    verified_ids = _verified_user_ids(schema_editor)
    if verified_ids:
        User.objects.using(schema_editor.connection.alias).filter(id__in=verified_ids).update(
            is_verified=True, verified_at=timezone_now()
        )

    # --- service menu --------------------------------------------------------
    profile_by_user = {
        profile.user_id: profile.id
        for profile in ProviderProfile.objects.using(schema_editor.connection.alias).all()
    }
    services = []
    seen: set[tuple[int, str]] = set()
    for row in _legacy_services(schema_editor):
        provider_id = profile_by_user.get(row["service_provider_id"])
        if provider_id is None:
            continue
        name = (row["service"] or "").strip() or "Service"
        # The new schema is unique on (provider, name); the old one was not.
        key = (provider_id, name.lower())
        if key in seen:
            continue
        seen.add(key)
        services.append(
            Service(
                provider_id=provider_id,
                name=name,
                description="",
                price=_strip_commission(row["cost"]),
                duration_minutes=30,
                is_active=True,
                created_at=timezone_now(),
                updated_at=timezone_now(),
            )
        )
    Service.objects.using(schema_editor.connection.alias).bulk_create(services, batch_size=500)

    # --- payouts -------------------------------------------------------------
    # Done in Python rather than SQL because the destination column is encrypted
    # with Fernet, and the key only exists in application code.
    payouts = []
    for row in _legacy_payouts(schema_editor):
        provider_id = profile_by_user.get(row["id"])
        if provider_id is None:
            continue
        payouts.append(
            ProviderPayout(
                provider_id=provider_id,
                business_name=row["business_name"] or "Unnamed business",
                business_type=row["business_type"] or "individual",
                beneficiary_name=row["beneficiary_name"] or "",
                account_number=str(row["account_number"] or ""),
                ifsc_code=(row["ifsc_code"] or "").upper(),
                account_type=row["account_type"] or "savings",
                razorpay_account_id=row["account_id"] or "",
                razorpay_destination=row["destination"] or "",
                verification_status="submitted",
                created_at=timezone_now(),
                updated_at=timezone_now(),
            )
        )
    if payouts:
        ProviderPayout.objects.using(schema_editor.connection.alias).bulk_create(
            payouts, batch_size=200
        )

    # --- obsolete credentials ------------------------------------------------
    # Plaintext codes with no expiry. VerificationCode replaces them; leaving
    # these would keep a table of unexpired password reset codes alive.
    schema_editor.execute("DELETE FROM accounts_signupcodes")
    schema_editor.execute("DELETE FROM accounts_passwordcodes")
    schema_editor.execute("DELETE FROM accounts_emails")


def reverse(apps, schema_editor):
    """There is no going back.

    The new model carries information the old one had nowhere to put — roles,
    ratings, encrypted bank details, line items with snapshotted prices. A
    reverse migration would have to invent all of it. Raising is the honest
    answer; restore from a backup instead.
    """
    raise NotImplementedError(
        "Migrating BarberShop profile data forward is not reversible. "
        "Restore from a database backup if you need to go back."
    )


# ---------------------------------------------------------------------------
# raw readers
# ---------------------------------------------------------------------------


def _table_exists(schema_editor, name: str) -> bool:
    """Whether a legacy table is present.

    A data migration that runs against a database where the legacy tables have
    already been dropped — a fresh install, or a re-run — has to be a no-op
    rather than an error. Every legacy read below is guarded accordingly.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", [name])
        return cursor.fetchone() is not None


def timezone_now():
    from django.utils import timezone

    return timezone.now()


def _legacy_profiles(schema_editor, table: str) -> list[dict]:
    """Read a legacy profile table, converting geometry coordinates to geography."""
    if not _table_exists(schema_editor, table):
        return []
    from django.contrib.gis.geos import GEOSGeometry

    # `id_id`, not `id`: these tables key off a OneToOneField whose primary key
    # points at accounts_user, so Django names the column after the field.
    columns = {
        "accounts_userdetails": "id_id AS id, about, contact, image, location",
        "accounts_barberdetails": (
            "id_id AS id, about, contact, employee_count, end_time, image, "
            "location, service_type, start_time"
        ),
    }[table]

    cursor = schema_editor.connection.cursor()
    cursor.execute(f"SELECT ST_AsText(coords::geography) AS geo, {columns} FROM {table}")
    names = [desc[0] for desc in cursor.description]
    rows = []
    for raw in cursor.fetchall():
        row = dict(zip(names, raw, strict=True))
        geo = row.pop("geo")
        row["coords"] = GEOSGeometry(geo, srid=4326) if geo else None
        if table == "accounts_barberdetails":
            row["display_name"] = _display_name(schema_editor, row["id"])
        rows.append(row)
    return rows


def _display_name(schema_editor, user_id: int) -> str:
    cursor = schema_editor.connection.cursor()
    cursor.execute(
        "SELECT COALESCE(NULLIF(btrim(first_name || ' ' || last_name), ''), username) "
        "FROM accounts_user WHERE id = %s",
        [user_id],
    )
    row = cursor.fetchone()
    return row[0] if row else f"Provider {user_id}"


def _legacy_services(schema_editor) -> list[dict]:
    if not _table_exists(schema_editor, "accounts_servicesdetails"):
        return []
    cursor = schema_editor.connection.cursor()
    cursor.execute("SELECT service_provider_id, service, cost FROM accounts_servicesdetails")
    return [
        {"service_provider_id": row[0], "service": row[1], "cost": row[2] or 0}
        for row in cursor.fetchall()
    ]


def _legacy_payouts(schema_editor) -> list[dict]:
    if not _table_exists(schema_editor, "accounts_bankdetails"):
        return []
    cursor = schema_editor.connection.cursor()
    cursor.execute(
        "SELECT id_id, business_name, business_type, beneficiary_name, account_number, "
        "ifsc_code, account_type, account_id, destination FROM accounts_bankdetails"
    )
    names = [
        "id",  # the barber's user id
        "business_name",
        "business_type",
        "beneficiary_name",
        "account_number",
        "ifsc_code",
        "account_type",
        "account_id",
        "destination",
    ]
    return [dict(zip(names, raw, strict=True)) for raw in cursor.fetchall()]


def _verified_user_ids(schema_editor) -> list[int]:
    if not _table_exists(schema_editor, "accounts_emails"):
        return []
    cursor = schema_editor.connection.cursor()
    cursor.execute("SELECT DISTINCT user_id FROM accounts_emails")
    return [row[0] for row in cursor.fetchall()]


VALID_SERVICE_TYPES = {
    "barbershop",
    "hair_salon",
    "beauty_salon",
    "full_service_salon",
    "spa",
    "massage",
    "other",
}


def _clean_service_type(value: str) -> str:
    value = (value or "").strip()
    return value if value in VALID_SERVICE_TYPES else "other"


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_customerprofile"),
        ("providers", "0001_initial"),
    ]

    operations = [migrations.RunPython(forward, reverse)]
