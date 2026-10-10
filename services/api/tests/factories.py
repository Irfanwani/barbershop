"""Test data builders.

Plain functions rather than a factory library: these are short, the call sites
read as English, and there is no dependency to keep in step with the models.

Usernames and tokens are auto-numbered so tests never collide on the unique
constraints — a collision surfaces as an ``IntegrityError`` that has nothing to
do with what the test is actually checking.
"""

from __future__ import annotations

import itertools
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.utils import timezone

from accounts.models import Role, User
from bookings.models import Booking, BookingItem, BookingStatus
from core.money import compute_platform_fee
from payments.models import Payment, PaymentStatus
from providers.models import ProviderProfile, Service, ServiceType
from reviews.models import Review

# Connaught Place, New Delhi. Two providers get slightly different points so
# distance queries have something to discriminate.
DELHI = Point(77.2090, 28.6139, srid=4326)
DELHI_NEAR = Point(77.2110, 28.6150, srid=4326)
DELHI_FAR = Point(77.3000, 28.6500, srid=4326)

_counter = itertools.count(1)


def unique(prefix: str = "u") -> str:
    return f"{prefix}{next(_counter)}"


def as_time(value: str | time | None, default: time) -> time:
    if value is None:
        return default
    if isinstance(value, time):
        return value
    return time.fromisoformat(value)


def make_user(
    username: str | None = None,
    *,
    role: str = Role.CUSTOMER,
    email: str | None = None,
    password: str = "Str0ngPass!23",
    verified: bool = True,
    **extra,
) -> User:
    username = username or unique("user")
    return User.objects.create_user(
        username=username,
        email=email or f"{username}@example.com",
        password=password,
        role=role,
        is_verified=verified,
        **({"verified_at": timezone.now()} if verified else {}),
        **extra,
    )


def make_provider_user(username: str | None = None, **kwargs) -> User:
    return make_user(username, role=Role.PROVIDER, **kwargs)


def make_profile(
    user: User | None = None,
    *,
    display_name: str = "Sharp Cuts Studio",
    coords: Point | None = None,
    service_type: str = ServiceType.BARBERSHOP,
    opening_time: str | time = time(9, 0),
    closing_time: str | time = time(20, 0),
    **kwargs,
) -> ProviderProfile:
    user = user or make_provider_user()
    return ProviderProfile.objects.create(
        user=user,
        display_name=display_name,
        service_type=service_type,
        coords=coords or DELHI,
        opening_time=as_time(opening_time, time(9, 0)),
        closing_time=as_time(closing_time, time(20, 0)),
        **kwargs,
    )


def make_service(
    profile: ProviderProfile,
    *,
    name: str = "Haircut",
    price: int = 25000,
    duration_minutes: int = 30,
    **kwargs,
) -> Service:
    return Service.objects.create(
        provider=profile,
        name=name,
        price=price,
        duration_minutes=duration_minutes,
        **kwargs,
    )


def next_slot(days: int = 1, hour: int = 12, minutes: int = 0) -> datetime:
    """A workable future start time, aligned to the provider's slot grid."""
    base = timezone.localtime(timezone.now() + timedelta(days=days))
    return base.replace(hour=hour, minute=minutes, second=0, microsecond=0)


def make_booking(
    *,
    customer: User | None = None,
    provider: ProviderProfile | None = None,
    service: Service | None = None,
    starts_at: datetime | None = None,
    status: str = BookingStatus.CONFIRMED,
    subtotal: int | None = None,
    platform_fee: int | None = None,
) -> Booking:
    customer = customer or make_user()
    provider = provider or make_profile()
    service = service or make_service(provider)

    starts_at = starts_at or next_slot()
    ends_at = starts_at + timedelta(minutes=service.duration_minutes)

    subtotal = service.price if subtotal is None else subtotal
    platform_fee = compute_platform_fee(subtotal, 10) if platform_fee is None else platform_fee

    booking = Booking.objects.create(
        customer=customer,
        provider=provider,
        starts_at=starts_at,
        ends_at=ends_at,
        status=status,
        subtotal=subtotal,
        platform_fee=platform_fee,
        total=subtotal + platform_fee,
    )
    BookingItem.objects.create(
        booking=booking,
        service=service,
        name=service.name,
        unit_price=service.price,
        quantity=1,
        duration_minutes=service.duration_minutes,
    )
    return booking


def make_payment(booking: Booking, *, status: str = PaymentStatus.CAPTURED) -> Payment:
    return Payment.objects.create(
        booking=booking,
        razorpay_order_id=f"order_{booking.reference.replace('-', '').lower()}",
        amount=booking.total,
        status=status,
        **({"captured_at": timezone.now()} if status == PaymentStatus.CAPTURED else {}),
    )


def make_review(
    *,
    customer: User | None = None,
    provider: ProviderProfile | None = None,
    rating: int = 5,
    booking: Booking | None = None,
    **kwargs,
) -> Review:
    return Review.objects.create(
        customer=customer or make_user(),
        provider=provider or make_profile(),
        rating=rating,
        booking=booking,
        **kwargs,
    )


def raw_column(table: str, column: str, pk: int) -> str:
    """Read a column straight from the database, bypassing Django's converters.

    Needed to prove that an encrypted field is genuinely encrypted on disk —
    ``values_list`` applies ``from_db_value`` and would hand back plaintext,
    making the assertion pass or fail for the wrong reason.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(f'SELECT "{column}" FROM "{table}" WHERE id = %s', [pk])
        row = cursor.fetchone()
    return row[0] if row else ""


def authenticate(client, user: User) -> str:
    """Log ``user`` in through the real login endpoint and return the token."""
    response = client.post(
        "/api/v1/auth/login/",
        {"username": user.username, "password": "Str0ngPass!23"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()["token"]


def auth_header(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Token {token}"}


def decimal(value: str) -> Decimal:
    return Decimal(value)
