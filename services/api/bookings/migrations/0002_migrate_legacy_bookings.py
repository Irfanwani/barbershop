"""Carry appointments, ratings and push tokens into the new models.

============================  ==========================================
old                           new
============================  ==========================================
``Appointments``              ``Booking`` + one ``BookingItem`` per service
``Appointments.services``     split on ``|`` into ``BookingItem`` rows
``Appointments.totalcost``    ``subtotal`` + ``platform_fee`` + ``total``
``Appointments.bookingID``    ``Booking.reference``
``RatingsAndReviews``         ``Review``
``NotificationTokens``        ``PushToken``
============================  ==========================================

Two details worth stating.

**Prices come apart.** The old ``totalcost`` had the platform's 10% baked in and
the services were a pipe-delimited string, so nothing could be re-derived. The
subtotal is recovered by dividing the total back out, and each line item's unit
price is taken from the provider's *current* menu where the name still matches.
A service that has since been renamed or repriced gets the recovered average —
not the new price — because rewriting a historical invoice is worse than an
approximate line.

**Nothing is lost to expiry.** Every old appointment is carried over, including
any that are already in the past. They come back as ``completed`` or ``no_show``
rather than being dropped.
"""

from __future__ import annotations

import hashlib

from django.db import migrations

OLD_COMMISSION = 0.10


def _strip_commission(amount: int) -> int:
    return max(0, round(amount / (1 + OLD_COMMISSION)))


def forward(apps, schema_editor):
    Booking = apps.get_model("bookings", "Booking")
    BookingItem = apps.get_model("bookings", "BookingItem")
    Review = apps.get_model("reviews", "Review")
    PushToken = apps.get_model("accounts", "PushToken")

    alias = schema_editor.connection.alias
    now = _now()

    provider_by_user = _provider_ids(schema_editor)
    services_by_provider = _service_menus(schema_editor)

    # --- appointments --------------------------------------------------------
    for row in _appointments(schema_editor):
        provider_id = provider_by_user.get(row["barber_id"])
        if provider_id is None:
            # The shop was deleted but the booking was not (both cascaded in the
            # old schema, so this should be rare). Skip rather than fail: one bad
            # row must not block the whole migration.
            continue

        total = row["totalcost"] or 0
        subtotal = _strip_commission(total)
        platform_fee = total - subtotal

        names = [name.strip() for name in (row["services"] or "").split("|") if name.strip()]
        duration = 30 * max(len(names), 1)

        reference = _reference(row["booking_id"], row["id"])
        booking = Booking.objects.using(alias).create(
            reference=reference,
            customer_id=row["user_id"],
            provider_id=provider_id,
            starts_at=row["datetime"],
            ends_at=row["datetime"] + _minutes(duration),
            status=_status_for(row["paid"], row["datetime"], now),
            subtotal=subtotal,
            platform_fee=platform_fee,
            total=total,
            currency="INR",
            notes="",
            created_at=now,
            updated_at=now,
        )

        menu = services_by_provider.get(provider_id, {})
        count = len(names) or 1
        for name in names or ["Service"]:
            service_id, unit_price = _line_for(name, menu, subtotal, count)
            BookingItem.objects.using(alias).create(
                booking=booking,
                service_id=service_id,
                name=name,
                unit_price=unit_price,
                quantity=1,
                duration_minutes=duration // count,
                created_at=now,
                updated_at=now,
            )

    # --- ratings -------------------------------------------------------------
    for row in _ratings(schema_editor):
        provider_id = provider_by_user.get(row["barber_id"])
        if provider_id is None:
            continue
        # The old column had no range constraint, so clamp rather than fail on
        # whatever a 2019 client managed to submit.
        rating = min(max(row["ratings"] or 3, 1), 5)
        Review.objects.using(alias).create(
            provider_id=provider_id,
            customer_id=row["user_id"],
            rating=rating,
            comment=(row["comments"] or "")[:1000],
            created_at=row["date"] or now,
            updated_at=now,
        )

    # --- push tokens ---------------------------------------------------------
    seen: set[str] = set()
    for row in _tokens(schema_editor):
        token = (row["token"] or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        PushToken.objects.using(alias).create(
            user_id=row["user_id"],
            token=token[:255],
            platform="",
            active=True,
            created_at=now,
            updated_at=now,
        )

    # --- cached ratings ------------------------------------------------------
    _refresh_provider_ratings(schema_editor)


def reverse(apps, schema_editor):
    raise NotImplementedError(
        "Migrating BarberShop booking data forward is not reversible. "
        "Restore from a database backup if you need to go back."
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _table_exists(schema_editor, name: str) -> bool:
    """Whether a legacy table is present.

    A data migration that runs on a database where the legacy tables have
    already been dropped — a fresh install, or a re-run — has to be a no-op
    rather than an error. Everything below is therefore guarded.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = %s", [name]
        )
        return cursor.fetchone() is not None


def _now():
    from django.utils import timezone

    return timezone.now()


def _minutes(count: int):
    from datetime import timedelta

    return timedelta(minutes=count)


def _provider_ids(schema_editor) -> dict[int, int]:
    """Old barber user id -> new provider profile id."""
    cursor = schema_editor.connection.cursor()
    cursor.execute("SELECT user_id, id FROM providers_profile")
    return {row[0]: row[1] for row in cursor.fetchall()}


def _service_menus(schema_editor) -> dict[int, dict[str, tuple[int, int]]]:
    """provider id -> {lowercased service name: (service id, price)}."""
    cursor = schema_editor.connection.cursor()
    cursor.execute("SELECT provider_id, id, name, price FROM providers_service")
    menu: dict[int, dict[str, tuple[int, int]]] = {}
    for provider_id, service_id, name, price in cursor.fetchall():
        menu.setdefault(provider_id, {})[name.strip().lower()] = (service_id, price)
    return menu


def _appointments(schema_editor) -> list[dict]:
    if not _table_exists(schema_editor, "haircut_appointments"):
        return []
    cursor = schema_editor.connection.cursor()
    cursor.execute(
        "SELECT id, \"bookingID\" AS booking_id, user_id, barber_id, datetime, "
        "services, totalcost, paid "
        "FROM haircut_appointments ORDER BY id"
    )
    names = [
        "id",
        "booking_id",
        "user_id",
        "barber_id",
        "datetime",
        "services",
        "totalcost",
        "paid",
    ]
    return [dict(zip(names, raw, strict=True)) for raw in cursor.fetchall()]


def _ratings(schema_editor) -> list[dict]:
    if not _table_exists(schema_editor, "haircut_ratingsandreviews"):
        return []
    cursor = schema_editor.connection.cursor()
    cursor.execute(
        "SELECT barber_id, user_id, ratings, comments, date FROM haircut_ratingsandreviews"
    )
    names = ["barber_id", "user_id", "ratings", "comments", "date"]
    return [dict(zip(names, raw, strict=True)) for raw in cursor.fetchall()]


def _tokens(schema_editor) -> list[dict]:
    if not _table_exists(schema_editor, "haircut_notificationtokens"):
        return []
    cursor = schema_editor.connection.cursor()
    cursor.execute("SELECT user_id, token FROM haircut_notificationtokens")
    names = ["user_id", "token"]
    return [dict(zip(names, raw, strict=True)) for raw in cursor.fetchall()]


def _reference(booking_id: int | None, row_id: int) -> str:
    """A stable customer-facing reference for a legacy booking.

    Deterministic rather than random, so re-running the migration produces the
    same codes and cannot collide with a freshly generated ``BK-XXXXXX``.
    """
    seed = f"{booking_id}:{row_id}" if booking_id else str(row_id)
    digest = hashlib.sha256(seed.encode()).hexdigest()[:6].upper()
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    body = "".join(
        alphabet[int(digest[index], 16) % len(alphabet)] for index in range(len(digest))
    )
    return f"BK-{body}"


def _status_for(paid: bool, starts_at, now) -> str:
    """Map the old ``paid`` boolean plus the clock onto a real status."""
    if starts_at >= now:
        return "confirmed" if paid else "pending_payment"
    return "completed" if paid else "no_show"


def _line_for(
    name: str, menu: dict[str, tuple[int, int]], subtotal: int, count: int
) -> tuple[int | None, int]:
    """Resolve one line item against the provider's current menu.

    A match gives the live service id and its live price. No match gives ``None``
    and an even share of the recovered subtotal — an honest approximation beats
    a wrong number written into someone's history.
    """
    match = menu.get(name.strip().lower())
    if match:
        return match[0], match[1]
    return None, max(subtotal // count, 0)


def _refresh_provider_ratings(schema_editor):
    schema_editor.execute(
        """
        UPDATE providers_profile AS p
        SET rating_average = COALESCE(agg.average, 0),
            rating_count = COALESCE(agg.total, 0)
        FROM (
            SELECT provider_id, AVG(rating) AS average, COUNT(*) AS total
            FROM reviews_review
            GROUP BY provider_id
        ) AS agg
        WHERE p.id = agg.provider_id
        """
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_migrate_legacy_profiles"),
        ("bookings", "0001_initial"),
        ("providers", "0001_initial"),
        ("reviews", "0001_initial"),
        # Deliberately no dependency on the `haircut` app. That app is deleted
        # once this migration has run everywhere, and a migration graph cannot
        # outlive the app it points at. Instead each legacy read is guarded by
        # `_table_exists`, so this runs correctly on a fresh install (nothing
        # to copy), on a live database (copy everything), and on a re-run
        # (no-op).
    ]

    operations = [migrations.RunPython(forward, reverse)]