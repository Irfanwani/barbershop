"""Tests for the domain model itself — constraints, defaults and invariants."""

from __future__ import annotations

import importlib
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from accounts.models import LoginAudit, PushToken, Role, VerificationCode
from bookings.models import (
    Booking,
    BookingStatus,
    generate_reference,
    is_slot_available,
    provider_has_capacity,
)
from core.fields import mask
from core.money import compute_platform_fee, format_minor, quote, to_minor
from payments.models import Payment, PaymentStatus
from providers.models import ProviderPayout, ProviderProfile
from reviews.models import MAX_RATING, MIN_RATING
from tests import factories
from tests.factories import make_user

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class TestUser:
    def test_role_defaults_to_customer(self):
        assert make_user().role == Role.CUSTOMER

    def test_is_provider_reflects_the_stored_role(self):
        """The old API inferred this from a profile row existing."""
        user = factories.make_user("shop", role=Role.PROVIDER)
        assert user.is_provider
        assert not user.is_customer

    def test_display_name_prefers_the_real_name(self):
        user = factories.make_user("jdoe", first_name="Jane", last_name="Doe")
        assert user.display_name == "Jane Doe"

    def test_display_name_falls_back_to_username(self):
        assert factories.make_user("jdoe").display_name == "jdoe"

    def test_email_is_unique(self):
        factories.make_user("one", email="same@example.com")
        with pytest.raises(IntegrityError):
            factories.make_user("two", email="same@example.com")

    def test_customer_onboarding_needs_only_verification(self):
        assert factories.make_user().onboarding_complete

    def test_unverified_customer_is_not_onboarded(self):
        assert not factories.make_user(verified=False).onboarding_complete

    def test_provider_onboarding_needs_a_profile_and_a_service(self):
        user = factories.make_provider_user()
        assert not user.onboarding_complete

        profile = factories.make_profile(user)
        assert not user.onboarding_complete, "a profile with no menu is not bookable"

        factories.make_service(profile)
        user.refresh_from_db()
        assert user.onboarding_complete

    def test_provider_profile_is_reachable_by_related_name(self):
        user = factories.make_provider_user()
        profile = factories.make_profile(user)
        assert user.provider_profile is profile

    def test_mark_verified_stamps_the_time(self):
        user = factories.make_user(verified=False)
        assert user.verified_at is None
        user.mark_verified()
        assert user.is_verified and user.verified_at is not None


# ---------------------------------------------------------------------------
# Verification codes
# ---------------------------------------------------------------------------


class TestVerificationCode:
    def test_code_is_hashed_not_stored(self):
        from core.tokens import generate_code, hash_code

        code = generate_code()
        record = VerificationCode.objects.create(
            user=factories.make_user(),
            purpose=VerificationCode.Purpose.SIGNUP,
            code_hash=hash_code(code),
            expires_at=timezone.now() + timedelta(days=1),
        )
        assert code not in record.code_hash
        assert record.code_hash == hash_code(code)

    def test_codes_use_an_unambiguous_alphabet(self):
        from core.tokens import CODE_ALPHABET, generate_code

        sample = {generate_code(200) for _ in range(50)}
        assert not set("".join(sample)) - set(CODE_ALPHABET)
        assert not set("IO01") & set("".join(sample))

    def test_matching_is_case_insensitive(self):
        from core.tokens import codes_match, generate_code, hash_code

        code = generate_code()
        assert codes_match(code.lower(), hash_code(code))
        assert not codes_match(generate_code() + "X", hash_code(code))

    def test_expired_code_is_not_usable(self):
        from core.tokens import hash_code

        record = VerificationCode.objects.create(
            user=factories.make_user(),
            purpose=VerificationCode.Purpose.RESET,
            code_hash=hash_code("ABCDEFGH"),
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        assert not record.is_usable

    def test_consumed_code_is_not_usable(self):
        from core.tokens import hash_code

        record = VerificationCode.objects.create(
            user=factories.make_user(),
            purpose=VerificationCode.Purpose.SIGNUP,
            code_hash=hash_code("ABCDEFGH"),
            expires_at=timezone.now() + timedelta(days=1),
        )
        record.consume()
        assert not record.is_usable


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class TestProviderProfile:
    def test_coordinates_round_trip(self):
        profile = factories.make_profile(coords=factories.DELHI)
        assert profile.latitude == pytest.approx(28.6139, abs=1e-6)
        assert profile.longitude == pytest.approx(77.2090, abs=1e-6)

    def test_starting_price_is_the_cheapest_active_service(self):
        profile = factories.make_profile()
        factories.make_service(profile, name="Beard trim", price=8000)
        factories.make_service(profile, name="Haircut", price=25000)
        factories.make_service(profile, name="Retired", price=100, is_active=False)
        assert profile.starting_price == 8000

    def test_starting_price_is_none_with_no_services(self):
        assert factories.make_profile().starting_price is None

    def test_service_names_are_unique_per_provider(self):
        profile = factories.make_profile()
        factories.make_service(profile, name="Haircut")
        with pytest.raises(IntegrityError):
            factories.make_service(profile, name="Haircut")

    def test_two_providers_may_offer_the_same_service(self):
        factories.make_service(factories.make_profile(), name="Haircut")
        factories.make_service(factories.make_profile(), name="Haircut")

    def test_service_cannot_be_deleted_out_from_under_a_booking(self):
        booking = factories.make_booking()
        item = booking.items.get()
        item.service.delete()
        item.refresh_from_db()
        assert item.service is None
        assert item.name == "Haircut", "the snapshot must survive"

    def test_is_open_at_respects_hours(self):
        profile = factories.make_profile(opening_time="09:00", closing_time="17:00")
        noon = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
        assert profile.is_open_at(noon)
        assert not profile.is_open_at(noon.replace(hour=18))

    def test_employee_count_must_be_at_least_one(self):
        with pytest.raises(IntegrityError):
            ProviderProfile.objects.create(
                user=factories.make_provider_user(),
                display_name="Nobody",
                coords=factories.DELHI,
                employee_count=0,
            )


# ---------------------------------------------------------------------------
# Payout — the encrypted one
# ---------------------------------------------------------------------------


class TestProviderPayout:
    def _payout(self, **kwargs):
        profile = factories.make_profile()
        defaults = {
            "provider": profile,
            "business_name": "Sharp Cuts Studio",
            "beneficiary_name": "Irfan Wani",
            "account_number": "4111111111111111",
            "ifsc_code": "HDFC0001234",
        }
        return ProviderPayout.objects.create(**{**defaults, **kwargs})

    def test_account_number_is_not_stored_in_plaintext(self):
        payout = self._payout()
        raw = factories.raw_column("providers_payout", "account_number", payout.id)
        assert "4111111111111111" not in raw
        assert raw.startswith("gAAAA"), "expected a Fernet token"

    def test_account_number_round_trips_through_the_orm(self):
        payout = self._payout()
        assert payout.account_number == "4111111111111111"

    def test_ifsc_code_is_encrypted(self):
        payout = self._payout()
        raw = factories.raw_column("providers_payout", "ifsc_code", payout.id)
        assert "HDFC0001234" not in raw

    def test_masked_account_number_keeps_only_the_last_four(self):
        payout = self._payout()
        assert payout.account_number_masked == "•" * 12 + "1111"
        assert "4111" not in payout.account_number_masked

    def test_mask_handles_short_values(self):
        assert mask("12") == "••"
        assert mask("") == ""

    def test_updating_one_field_does_not_double_encrypt(self):
        payout = self._payout()
        payout.business_name = "Renamed Studio"
        payout.save()
        payout.refresh_from_db()
        assert payout.account_number == "4111111111111111"


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


class TestMoney:
    def test_minor_units_round_trip(self):
        assert to_minor(250.50) == 25050
        assert to_minor("0.01") == 1

    def test_formatting_uses_the_currency_symbol(self):
        assert format_minor(25050) == "₹250.50"
        assert format_minor(25050, "USD") == "USD 250.50"

    def test_platform_fee_rounds_half_up(self):
        assert compute_platform_fee(101, 10) == 10
        assert compute_platform_fee(105, 10) == 11
        assert compute_platform_fee(1005, 10) == 101

    def test_platform_fee_is_zero_when_disabled(self):
        assert compute_platform_fee(10000, 0) == 0

    def test_quote_sums_lines_and_fee(self):
        result = quote([(1, "Haircut", 20000, 30), (2, "Beard trim", 5000, 15)], fee_percent=10)
        assert result.subtotal == 25000
        assert result.platform_fee == 2500
        assert result.total == 27500
        assert result.duration_minutes == 45

    def test_quote_is_rendered_for_display(self):
        rendered = quote([(1, "Haircut", 20000, 30)], fee_percent=10).as_dict()
        assert rendered["display"]["total"] == "₹220.00"

    def test_the_default_fee_is_one_percent(self, monkeypatch):
        # Re-read from the settings module with the variable unset, rather than
        # asserting on django.conf.settings: a developer's local .env must not
        # be able to quietly move this number.
        monkeypatch.delenv("PLATFORM_FEE_PERCENT", raising=False)
        base = importlib.reload(importlib.import_module("config.settings.base"))

        assert base.PLATFORM_FEE_PERCENT == 1
        # And it is a real percent, not a string that only works by accident.
        assert compute_platform_fee(10000, base.PLATFORM_FEE_PERCENT) == 100

    def test_one_percent_of_a_realistic_price(self):
        # A ₹400 haircut: the fee is ₹4, not ₹40. Providers set the price, and
        # a default that quietly takes a tenth of it is a default nobody asked for.
        assert compute_platform_fee(40000, 1) == 400

    def test_one_percent_of_a_cheap_service_does_not_round_away(self):
        # A ₹5 trim at 1% is 5 paise. Rounding this to zero would make the fee
        # disappear on small bookings and make the tax arithmetic inconsistent.
        assert compute_platform_fee(500, 1) == 5

    def test_the_fee_is_never_negative_or_absurd(self):
        assert compute_platform_fee(100, 1) == 1
        assert compute_platform_fee(1, 1) == 0
        assert compute_platform_fee(1, 10) == 0


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------


class TestBooking:
    def test_reference_is_prefixed_and_not_sequential(self):
        references = {generate_reference() for _ in range(200)}
        assert all(ref.startswith("BK-") for ref in references)
        assert len(references) == 200, "references must not collide"

    def test_reference_excludes_ambiguous_characters(self):
        assert not set("IO01") & set(generate_reference())

    def test_ends_at_must_be_after_starts_at(self):
        with pytest.raises(IntegrityError):
            factories.make_booking().__class__.objects.create(
                customer=factories.make_user(),
                provider=factories.make_profile(),
                starts_at=factories.next_slot(),
                ends_at=factories.next_slot() - timedelta(minutes=5),
            )

    def test_total_cannot_be_less_than_subtotal(self):
        with pytest.raises(IntegrityError):
            Booking.objects.create(
                customer=factories.make_user(),
                provider=factories.make_profile(),
                starts_at=factories.next_slot(),
                ends_at=factories.next_slot() + timedelta(minutes=30),
                subtotal=10000,
                total=500,
            )

    def test_item_snapshot_survives_a_price_change(self):
        booking = factories.make_booking()
        item = booking.items.get()
        item.service.price = 99999
        item.service.save()
        item.refresh_from_db()
        assert item.unit_price == 25000

    def test_total_display(self):
        assert factories.make_booking().total_display == "₹252.50"

    @pytest.mark.parametrize(
        "status,expected",
        [
            (BookingStatus.CONFIRMED, True),
            (BookingStatus.COMPLETED, False),
            (BookingStatus.CANCELLED_BY_CUSTOMER, False),
            (BookingStatus.REFUNDED, False),
        ],
    )
    def test_can_be_cancelled(self, status, expected):
        assert factories.make_booking(status=status).can_be_cancelled is expected

    def test_cancelled_statuses_are_terminal(self):
        assert BookingStatus.CANCELLED_BY_CUSTOMER.is_terminal
        assert not BookingStatus.CONFIRMED.is_terminal


class TestSlotAvailability:
    def test_free_slot_is_available(self):
        profile = factories.make_profile()
        start = factories.next_slot(hour=14)
        assert is_slot_available(profile, start, start + timedelta(minutes=30))

    def test_overlapping_booking_blocks_the_slot(self):
        booking = factories.make_booking(starts_at=factories.next_slot(hour=14))
        start = booking.starts_at + timedelta(minutes=15)
        assert not is_slot_available(booking.provider, start, start + timedelta(minutes=30))

    def test_adjacent_booking_does_not_block(self):
        """A booking ending exactly when another starts is not a conflict."""
        booking = factories.make_booking(starts_at=factories.next_slot(hour=14))
        assert is_slot_available(
            booking.provider, booking.ends_at, booking.ends_at + timedelta(minutes=30)
        )

    def test_cancelled_booking_frees_the_slot(self):
        booking = factories.make_booking(
            starts_at=factories.next_slot(hour=14),
            status=BookingStatus.CANCELLED_BY_CUSTOMER,
        )
        assert is_slot_available(booking.provider, booking.starts_at, booking.ends_at)

    def test_capacity_allows_one_per_employee(self):
        profile = factories.make_profile(employee_count=1)
        start = factories.next_slot(hour=15)
        factories.make_booking(provider=profile, starts_at=start)

        assert not provider_has_capacity(profile, start, start + timedelta(minutes=30))

        profile.employee_count = 2
        profile.save()
        assert provider_has_capacity(profile, start, start + timedelta(minutes=30))

    def test_cancelling_frees_capacity(self):
        profile = factories.make_profile(employee_count=1)
        start = factories.next_slot(hour=16)
        factories.make_booking(provider=profile, starts_at=start, status=BookingStatus.NO_SHOW)
        assert provider_has_capacity(profile, start, start + timedelta(minutes=30))


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


class TestReview:
    @pytest.mark.parametrize("rating", [MIN_RATING, 3, MAX_RATING])
    def test_rating_within_range_is_accepted(self, rating):
        assert factories.make_review(rating=rating).rating == rating

    @pytest.mark.parametrize("rating", [0, 6, 100])
    def test_rating_outside_range_is_rejected(self, rating):
        with pytest.raises(IntegrityError):
            factories.make_review(rating=rating)

    def test_rating_outside_range_fails_field_validation(self):
        review = factories.make_review()
        review.rating = 9
        with pytest.raises(ValidationError):
            review.full_clean()

    def test_only_one_review_per_booking(self):
        booking = factories.make_booking()
        factories.make_review(booking=booking)
        with pytest.raises(IntegrityError):
            factories.make_review(booking=booking)

    def test_rating_average_is_recomputed(self):
        profile = factories.make_profile()
        factories.make_review(provider=profile, rating=5)
        factories.make_review(provider=profile, rating=4)

        profile.refresh_rating()
        assert profile.rating_count == 2
        assert profile.rating_average == Decimal("4.50")


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


class TestPayment:
    def test_a_booking_has_at_most_one_payment(self):
        booking = factories.make_booking()
        factories.make_payment(booking)
        with pytest.raises(IntegrityError):
            factories.make_payment(booking, status=PaymentStatus.FAILED)

    def test_is_captured_reflects_status(self):
        booking = factories.make_booking()
        captured = factories.make_payment(booking, status=PaymentStatus.CAPTURED)
        assert captured.is_captured

        failed = factories.make_payment(factories.make_booking(), status=PaymentStatus.FAILED)
        assert not failed.is_captured

    def test_booking_reports_whether_it_was_paid(self):
        booking = factories.make_booking()
        assert not booking.is_paid
        factories.make_payment(booking)
        booking.refresh_from_db()
        assert booking.is_paid

    def test_deleting_a_booking_takes_its_payment_with_it(self):
        booking = factories.make_booking()
        factories.make_payment(booking)
        booking.delete()
        assert Payment.objects.count() == 0


# ---------------------------------------------------------------------------
# Push tokens
# ---------------------------------------------------------------------------


class TestPushToken:
    def test_token_is_unique_across_users(self):
        factories.make_user("one")
        factories.make_user("two")
        PushToken.objects.create(user_id=1, token="ExponentPushToken[abc]")
        with pytest.raises(IntegrityError):
            PushToken.objects.create(user_id=2, token="ExponentPushToken[abc]")

    def test_login_audit_records_failures(self):
        audit = LoginAudit.objects.create(
            email_attempted="nobody@example.com", succeeded=False, reason="bad password"
        )
        assert not audit.succeeded
        assert "failed" in str(audit)
