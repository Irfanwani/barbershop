"""Seed the database with a realistic demo.

    uv run python manage.py seed_demo

Refuses to touch a database that already has providers, unless ``--force`` is
passed. Seeding over real data is not a mistake worth allowing by default.
"""

from __future__ import annotations

import random
from datetime import time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Role, User
from bookings.models import Booking, BookingItem, BookingStatus
from core.money import compute_platform_fee
from providers.models import ProviderPayout, ProviderProfile, Service, ServiceType
from reviews.models import Review

DELHI = [
    ("Connaught Place", 77.2090, 28.6139),
    ("Sector 18, Dwarka", 77.0270, 28.5520),
    ("Karol Bagh", 77.1900, 28.6510),
    ("Nehru Place", 77.2580, 28.5670),
    ("Janakpuri", 77.0670, 28.6290),
]

SHOPS = [
    ("Sharp Cuts Studio", ServiceType.BARBERSHOP, "Traditional barbering since 2011."),
    ("The Fade Room", ServiceType.BARBERSHOP, "Fades, tapers and beard work."),
    ("Glow & Co", ServiceType.BEAUTY_SALON, "Facials, waxing and skin care."),
    ("Saffron Spa", ServiceType.SPA, "Deep tissue massage and head spa."),
    ("Locksmith", ServiceType.HAIR_SALON, "Cuts, colour and treatments."),
    ("Full Service Barbers", ServiceType.FULL_SERVICE_SALON, "Everything under one roof."),
]

MENUS = [
    [
        ("Haircut", 25000, 30),
        ("Beard trim", 10000, 15),
        ("Head shave", 40000, 45),
        ("Hair wash", 8000, 15),
    ],
    [
        ("Skin fade", 35000, 45),
        ("Beard sculpt", 15000, 20),
        ("Kids haircut", 18000, 20),
    ],
    [
        ("Facial", 55000, 60),
        ("Waxing", 30000, 30),
        ("Clean-up", 20000, 20),
    ],
    [
        ("Head spa", 65000, 60),
        ("Deep tissue massage", 75000, 60),
    ],
    [
        ("Haircut", 28000, 30),
        ("Colour", 120000, 90),
        ("Blow dry", 20000, 25),
    ],
]

COMMENTS = [
    "Exactly what I asked for. Booked again.",
    "Clean work, on time, good value.",
    "Friendly and thorough. Happy with the result.",
    "Slight wait but the cut was worth it.",
    "Great value for the price.",
]


class Command(BaseCommand):
    help = "Populate the database with demo providers, services and bookings."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Seed even if providers already exist.",
        )
        parser.add_argument(
            "--customers",
            type=int,
            default=12,
            help="How many demo customer accounts to create.",
        )
        parser.add_argument(
            "--bookings",
            type=int,
            default=40,
            help="How many demo bookings to create.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        if ProviderProfile.objects.exists() and not options["force"]:
            raise CommandError(
                "This database already has providers. Pass --force if you really "
                "mean to add demo data alongside them."
            )

        random.seed(20261010)  # Same demo data every time, which makes bugs reproducible.

        customers = self._create_customers(options["customers"])
        providers = self._create_providers()
        bookings = self._create_bookings(providers, customers, options["bookings"])
        self._create_reviews(providers, customers)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(providers)} providers, {len(customers)} customers "
                f"and {bookings} bookings."
            )
        )
        self.stdout.write(
            "Sign in as a provider with any password, e.g. "
            "provider1@example.com / Provider!123 (or customer1@example.com / Customer!123)"
        )

    # -- creators -------------------------------------------------------------

    def _make_user(self, prefix: str, index: int, role: Role) -> User:
        """Create a demo account with a predictable email and password.

        Idempotent, so ``--force`` adds to an existing demo set rather than
        colliding with it.
        """
        user, created = User.objects.get_or_create(
            username=f"{prefix}{index}",
            defaults={
                "email": f"{prefix}{index}@example.com",
                "role": role,
                "is_verified": True,
                "verified_at": timezone.now(),
                "first_name": f"Demo {index}",
            },
        )
        if created:
            user.set_password(f"{prefix.capitalize()}!123")
            user.save(update_fields=["password"])
        return user

    def _create_customers(self, count: int) -> list[User]:
        from django.contrib.gis.geos import Point

        from accounts.models import CustomerProfile

        customers = []
        for index in range(1, count + 1):
            user = self._make_user("customer", index, Role.CUSTOMER)
            _, lng, lat = random.choice(DELHI)
            CustomerProfile.objects.update_or_create(
                user=user,
                defaults={
                    "address": random.choice(DELHI)[0],
                    "about": "",
                    "coords": Point(lng, lat, srid=4326),
                },
            )
            customers.append(user)
        return customers

    def _create_providers(self) -> list[ProviderProfile]:
        from django.contrib.gis.geos import Point

        providers = []
        for index, (name, service_type, description) in enumerate(SHOPS, start=1):
            user = self._make_user("provider", index, Role.PROVIDER)
            area, lng, lat = DELHI[index % len(DELHI)]
            # Scatter shops a little around their neighbourhood.
            profile, _ = ProviderProfile.objects.update_or_create(
                user=user,
                defaults={
                    "display_name": name,
                    "description": description,
                    "service_type": service_type,
                    "address": f"{area}, New Delhi",
                    "coords": Point(
                        lng + random.uniform(-0.01, 0.01),
                        lat + random.uniform(-0.01, 0.01),
                        srid=4326,
                    ),
                    "contact_phone": f"+9111000{index:05d}",
                    "employee_count": random.choice([1, 2, 3, 4]),
                    "opening_time": time(9, 0),
                    "closing_time": random.choice([time(19), time(20), time(21)]),
                    "is_accepting_bookings": True,
                },
            )

            for service_name, price, duration in MENUS[index % len(MENUS)]:
                Service.objects.update_or_create(
                    provider=profile,
                    name=service_name,
                    defaults={
                        "description": "",
                        "price": price,
                        "duration_minutes": duration,
                    },
                )

            ProviderPayout.objects.update_or_create(
                provider=profile,
                defaults={
                    "business_name": f"{name} LLP",
                    "business_type": "proprietorship",
                    "beneficiary_name": f"Demo Provider {index}",
                    "account_number": f"{(1000000000000000 + index):016d}",
                    "ifsc_code": "HDFC0001234",
                    "account_type": "savings",
                    "verification_status": ProviderPayout.VerificationStatus.VERIFIED,
                },
            )

            providers.append(profile)
        return providers

    def _create_bookings(
        self, providers: list[ProviderProfile], customers: list[User], count: int
    ) -> int:
        now = timezone.now()
        created = 0

        attempts = 0
        # Candidates that fall outside opening hours are rejected, so keep
        # trying until we have the requested number or run out of patience.
        while created < count and attempts < count * 5:
            attempts += 1
            provider = random.choice(providers)
            customer = random.choice(customers)
            service = random.choice(list(provider.services.all()))

            # Spread across the last fortnight and the next week.
            starts_at = now + timedelta(
                days=random.randint(-14, 7),
                hours=random.choice([10, 11, 12, 15, 16, 17, 18]),
                minutes=random.choice([0, 30]),
            )
            ends_at = starts_at + timedelta(minutes=service.duration_minutes)
            if (
                not provider.opening_time
                <= timezone.localtime(starts_at).time()
                <= provider.closing_time
            ):
                continue

            in_the_past = starts_at < now
            paid = random.random() > 0.2

            status = (
                BookingStatus.COMPLETED
                if in_the_past and paid
                else BookingStatus.NO_SHOW
                if in_the_past
                else BookingStatus.CONFIRMED
                if paid
                else BookingStatus.PENDING_PAYMENT
            )

            platform_fee = compute_platform_fee(service.price, settings.PLATFORM_FEE_PERCENT)

            booking = Booking.objects.create(
                customer=customer,
                provider=provider,
                starts_at=starts_at,
                ends_at=ends_at,
                status=status,
                subtotal=service.price,
                platform_fee=platform_fee,
                total=service.price + platform_fee,
                notes="",
            )
            BookingItem.objects.create(
                booking=booking,
                service=service,
                name=service.name,
                unit_price=service.price,
                quantity=1,
                duration_minutes=service.duration_minutes,
            )
            created += 1

        if created < count:
            self.stdout.write(
                self.style.WARNING(
                    f"Only {created} of {count} requested bookings fitted inside opening hours."
                )
            )
        return created

    def _create_reviews(self, providers, customers) -> None:
        for profile in providers:
            for _ in range(random.randint(3, 12)):
                Review.objects.create(
                    provider=profile,
                    customer=random.choice(customers),
                    rating=random.choices([5, 4, 3, 2, 1], weights=[6, 3, 1, 0, 0])[0],
                    comment=random.choice(COMMENTS),
                )
            profile.refresh_rating()
