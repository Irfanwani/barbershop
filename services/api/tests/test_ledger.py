"""The provider ledger and withdrawals.

This is the feature that makes the platform a marketplace rather than a booking
form. Before it, a provider could save bank details and there was nowhere to
see what they had earned, let alone take it.

The property everything rests on: **the balance is derived from an append-only
ledger, never stored.** A stored balance that is updated in place is a balance
that will eventually be wrong with nothing to reconcile against, so the tests
here are largely about whether that derivation stays true.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from payments.ledger import (
    EntryKind,
    balance_for,
    credit_earning,
    debit,
    record_payout,
)
from payments.models import LedgerEntry
from payments.settle import settle_transfer
from providers.models import ProviderPayout
from tests.factories import auth_header, logged_in, make_profile, make_service, make_user

GROSS = 20000

pytestmark = pytest.mark.django_db

V1 = "/api/v1"
PROVIDERS = f"{V1}/providers/"


@pytest.fixture(autouse=True)
def razorpay(monkeypatch):
    """Record transfers instead of sending them."""
    sent: list[dict] = []

    def _create_payout(*, account_id, amount, reference, notes=None):
        sent.append({"account_id": account_id, "amount": amount, "reference": reference})
        return {"id": f"payout_{len(sent)}", "status": "processing"}

    monkeypatch.setattr("payments.services.create_payout", _create_payout, raising=False)
    return sent


def net_for(gross: int) -> int:
    """What a provider is owed after the platform's share.

    Computed from the live setting rather than hardcoded, so a change to the fee
    does not make every test in this file lie.
    """
    from payments.ledger import _fee_for

    return gross - _fee_for(gross)


def shop(*, verified=True):
    provider = make_profile()
    make_service(provider, price=20000)
    ProviderPayout.objects.create(
        provider=provider,
        business_name="Sharp Cuts",
        beneficiary_name="Jane Doe",
        account_number="4111111111111111",
        ifsc_code="HDFC0000053",
        verification_status=(
            ProviderPayout.VerificationStatus.VERIFIED
            if verified
            else ProviderPayout.VerificationStatus.SUBMITTED
        ),
        razorpay_destination="fnd_test" if verified else "",
    )
    return provider


# ---------------------------------------------------------------------------
# The balance
# ---------------------------------------------------------------------------


class TestBalance:
    def test_is_nothing_before_anything_happens(self):
        assert balance_for(shop()).total == 0

    def test_earnings_appear_as_pending_first(self):
        # A booking that has not finished can still be refunded or become a
        # no-show, so it is not money the provider can count on yet.
        provider = shop()
        credit_earning(provider, gross=20000, booking_reference="BK-1")

        balance = balance_for(provider)
        assert balance.pending == net_for(GROSS)
        assert balance.cleared == 0

    def test_an_earning_becomes_cleared(self):
        provider = shop()
        credit_earning(provider, gross=20000, booking_reference="BK-1")
        LedgerEntry.objects.filter(provider=provider).update(status=LedgerEntry.Status.CLEARED)

        balance = balance_for(provider)
        assert balance.cleared == net_for(GROSS)
        assert balance.pending == 0

    def test_the_fee_is_shown_rather_than_hidden_in_a_net_number(self):
        provider = shop()
        credit_earning(provider, gross=20000, booking_reference="BK-1")

        kinds = dict(LedgerEntry.objects.filter(provider=provider).values_list("kind", "amount"))
        # A shop asking "why is this 19,980 not 20,000" deserves a row saying so.
        assert kinds[EntryKind.EARNING] == GROSS
        assert kinds[EntryKind.PLATFORM_FEE] == -(GROSS - net_for(GROSS))

    def test_the_balance_is_always_the_sum_of_the_ledger(self):
        # The property the whole design rests on.
        provider = shop()
        for index in range(5):
            credit_earning(provider, gross=20000 + index, booking_reference=f"BK-{index}")
        debit(provider, kind=EntryKind.ADJUSTMENT, amount=500, description="Goodwill")
        # Earnings must be cleared before they can be paid out; the withdrawal
        # endpoint refuses otherwise.
        LedgerEntry.objects.filter(provider=provider).update(status=LedgerEntry.Status.CLEARED)
        record_payout(provider, amount=1000, reference="wd_test")

        earned = LedgerEntry.objects.filter(
            provider=provider, status__in=[LedgerEntry.Status.PENDING, LedgerEntry.Status.CLEARED]
        ).aggregate(total=models_sum())["total"]
        withdrawn = abs(
            LedgerEntry.objects.filter(
                provider=provider, status=LedgerEntry.Status.PAID_OUT
            ).aggregate(total=models_sum())["total"]
        )

        # Earnings minus what has been paid out. This equality is the property
        # the whole design exists to guarantee.
        assert balance_for(provider).total == max(earned - withdrawn, 0)

    def test_a_payout_lowers_the_balance(self):
        provider = shop()
        credit_earning(provider, gross=20000, booking_reference="BK-1")
        LedgerEntry.objects.filter(provider=provider).update(status=LedgerEntry.Status.CLEARED)

        record_payout(provider, amount=10000, reference="wd_test")

        balance = balance_for(provider)
        assert balance.total == net_for(GROSS) - 10000
        assert balance.paid_out == 10000

    def test_paid_out_money_is_not_owed_again(self):
        provider = shop()
        credit_earning(provider, gross=20000, booking_reference="BK-1")
        LedgerEntry.objects.filter(provider=provider).update(status=LedgerEntry.Status.CLEARED)
        record_payout(provider, amount=net_for(GROSS), reference="wd_test")

        # Otherwise a provider is shown money they have already been given.
        assert balance_for(provider).total == 0

    def test_two_providers_never_share_a_balance(self):
        one, other = shop(), shop()
        credit_earning(one, gross=20000, booking_reference="BK-1")

        assert balance_for(one).total == net_for(GROSS)
        assert balance_for(other).total == 0

    def test_a_zero_line_is_refused(self):
        # It explains nothing and only adds noise to a statement.
        from django.db.utils import IntegrityError

        provider = shop()
        with pytest.raises(IntegrityError):
            LedgerEntry.objects.create(
                provider=provider,
                kind=EntryKind.ADJUSTMENT,
                amount=0,
                status=LedgerEntry.Status.CLEARED,
            )


def models_sum():
    from django.db.models import Sum

    return Sum("amount")


# ---------------------------------------------------------------------------
# Earning
# ---------------------------------------------------------------------------


class TestEarning:
    def _complete_a_booking(self, client, provider, gross=20000):
        customer = make_user()
        starts_at = timezone.now() - timezone.timedelta(hours=1)
        service = provider.services.first()
        booking = Booking.objects.create(
            customer=customer,
            provider=provider,
            starts_at=starts_at,
            ends_at=starts_at + timezone.timedelta(minutes=30),
            subtotal=gross,
            platform_fee=gross // 100,
            total=gross + gross // 100,
            status=BookingStatus.CONFIRMED,
        )
        booking.items.create(service=service, name=service.name, unit_price=gross, quantity=1)
        provider_client, token = logged_in(provider.user)
        provider_client.post(
            f"{V1}/bookings/{booking.reference}/complete/",
            {},
            content_type="application/json",
            **auth_header(token),
        )
        return booking

    def test_completing_a_booking_credits_the_provider(self):
        provider = shop()
        self._complete_a_booking(None, provider)

        assert balance_for(provider).total == net_for(GROSS)

    def test_completing_twice_does_not_pay_twice(self):
        provider = shop()
        booking = self._complete_a_booking(None, provider)

        provider_client, token = logged_in(provider.user)
        # The second call is refused as an invalid transition, but a booking that
        # somehow got there twice must not double-credit.
        provider_client.post(
            f"{V1}/bookings/{booking.reference}/complete/",
            {},
            content_type="application/json",
            **auth_header(token),
        )

        assert balance_for(provider).total == net_for(GROSS)

    def test_a_no_show_earns_nothing(self):
        provider = shop()
        customer = make_user()
        starts_at = timezone.now() - timezone.timedelta(hours=1)
        service = provider.services.first()
        booking = Booking.objects.create(
            customer=customer,
            provider=provider,
            starts_at=starts_at,
            ends_at=starts_at + timezone.timedelta(minutes=30),
            subtotal=20000,
            platform_fee=200,
            total=20200,
            status=BookingStatus.CONFIRMED,
        )
        booking.items.create(service=service, name=service.name, unit_price=20000, quantity=1)

        client, token = logged_in(provider.user)
        client.post(
            f"{V1}/bookings/{booking.reference}/no-show/",
            {},
            content_type="application/json",
            **auth_header(token),
        )

        assert balance_for(provider).total == 0

    def test_cancelling_does_not_earn_anything(self):
        provider = shop()
        customer = make_user()
        starts_at = timezone.now() + timezone.timedelta(hours=48)
        service = provider.services.first()
        booking = Booking.objects.create(
            customer=customer,
            provider=provider,
            starts_at=starts_at,
            ends_at=starts_at + timezone.timedelta(minutes=30),
            subtotal=20000,
            platform_fee=200,
            total=20200,
            status=BookingStatus.CONFIRMED,
        )
        booking.items.create(service=service, name=service.name, unit_price=20000, quantity=1)

        customer_client, token = logged_in(customer)
        customer_client.post(
            f"{V1}/bookings/{booking.reference}/cancel/",
            {"reason": "changed my mind"},
            content_type="application/json",
            **auth_header(token),
        )

        assert balance_for(provider).total == 0


# ---------------------------------------------------------------------------
# Withdrawing
# ---------------------------------------------------------------------------


class TestWithdrawal:
    def _cleared(self, provider, gross=20000):
        credit_earning(provider, gross=gross, booking_reference="BK-1")
        LedgerEntry.objects.filter(provider=provider).update(status=LedgerEntry.Status.CLEARED)

    def test_a_provider_can_take_their_cleared_money(self, razorpay):
        provider = shop()
        self._cleared(provider)
        client, token = logged_in(provider.user)

        response = client.post(
            f"{PROVIDERS}me/withdraw/",
            {},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200, response.content
        assert response.data["withdrawal"]["amount"] == net_for(GROSS)
        assert razorpay[0]["amount"] == net_for(GROSS)
        assert balance_for(provider).total == 0

    def test_the_money_leaves_our_balance_immediately(self, razorpay):
        # It has left either way, whether or not the bank has settled it. Showing
        # it as still theirs would invite them to withdraw twice.
        provider = shop()
        self._cleared(provider)
        client, token = logged_in(provider.user)

        client.post(
            f"{PROVIDERS}me/withdraw/", {}, content_type="application/json", **auth_header(token)
        )

        assert balance_for(provider).total == 0

    def test_pending_earnings_cannot_be_withdrawn(self, razorpay):
        # A booking that has not finished can still be refunded or become a
        # no-show.
        provider = shop()
        credit_earning(provider, gross=20000, booking_reference="BK-1")
        client, token = logged_in(provider.user)

        response = client.post(
            f"{PROVIDERS}me/withdraw/", {}, content_type="application/json", **auth_header(token)
        )

        assert response.status_code == 400
        assert razorpay == []

    def test_withdrawing_more_than_the_balance_is_refused(self, razorpay):
        provider = shop()
        self._cleared(provider)
        client, token = logged_in(provider.user)

        response = client.post(
            f"{PROVIDERS}me/withdraw/",
            {"amount": 50000},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400
        assert razorpay == []
        assert balance_for(provider).total == net_for(GROSS)

    def test_a_partial_withdrawal_leaves_the_rest(self, razorpay):
        provider = shop()
        self._cleared(provider)
        client, token = logged_in(provider.user)

        client.post(
            f"{PROVIDERS}me/withdraw/",
            {"amount": 5000},
            content_type="application/json",
            **auth_header(token),
        )

        assert balance_for(provider).total == net_for(GROSS) - 5000

    def test_an_unverified_account_is_not_paid(self, razorpay):
        # Moving money on a promise.
        provider = shop(verified=False)
        self._cleared(provider)
        client, token = logged_in(provider.user)

        response = client.post(
            f"{PROVIDERS}me/withdraw/", {}, content_type="application/json", **auth_header(token)
        )

        assert response.status_code == 400
        assert "not verified" in response.data["error"]["message"]
        assert razorpay == []

    def test_a_provider_with_no_bank_details_is_not_paid(self, razorpay):
        provider = make_profile()
        make_service(provider)
        credit_earning(provider, gross=20000)
        LedgerEntry.objects.filter(provider=provider).update(status=LedgerEntry.Status.CLEARED)
        client, token = logged_in(provider.user)

        response = client.post(
            f"{PROVIDERS}me/withdraw/", {}, content_type="application/json", **auth_header(token)
        )

        assert response.status_code == 400

    def test_a_gateway_outage_still_leaves_the_balance(self, monkeypatch):
        # We tell the provider the money is on its way and a reconciliation job
        # settles it. Leaving the balance intact would let them withdraw the same
        # money again.
        provider = shop()
        credit_earning(provider, gross=20000)
        LedgerEntry.objects.filter(provider=provider).update(status=LedgerEntry.Status.CLEARED)

        def boom(**kwargs):
            raise ConnectionError("gateway down")

        monkeypatch.setattr("payments.services.create_payout", boom)

        client, token = logged_in(provider.user)
        response = client.post(
            f"{PROVIDERS}me/withdraw/", {}, content_type="application/json", **auth_header(token)
        )

        assert response.status_code == 200
        assert balance_for(provider).total == 0

    def test_a_customer_cannot_withdraw(self, razorpay):
        provider = shop()
        self._cleared(provider)
        client, token = logged_in(make_user())

        assert (
            client.post(
                f"{PROVIDERS}me/withdraw/",
                {},
                content_type="application/json",
                **auth_header(token),
            ).status_code
            == 403
        )

    def test_a_stranger_cannot_read_your_ledger(self):
        shop()
        client, token = logged_in(make_provider_user())

        assert client.get(f"{PROVIDERS}me/ledger/", **auth_header(token)).status_code == 403


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


class TestSettlement:
    def _requested(self, provider):
        credit_earning(provider, gross=20000)
        LedgerEntry.objects.filter(provider=provider).update(status=LedgerEntry.Status.CLEARED)
        client, token = logged_in(provider.user)
        body = client.post(
            f"{PROVIDERS}me/withdraw/", {}, content_type="application/json", **auth_header(token)
        ).data
        return body["withdrawal"]

    def test_a_settled_transfer_is_recorded_as_paid_out(self):
        provider = shop()
        withdrawal = self._requested(provider)

        settle_transfer(
            provider,
            reference=withdrawal["reference"],
            transfer_id=withdrawal["transfer_id"],
            succeeded=True,
        )

        balance = balance_for(provider)
        assert balance.total == 0
        assert balance.paid_out == net_for(GROSS)

    def test_a_failed_transfer_returns_the_money(self):
        # The provider never received it, so it is still theirs.
        provider = shop()
        withdrawal = self._requested(provider)

        settle_transfer(
            provider,
            reference=withdrawal["reference"],
            transfer_id=withdrawal["transfer_id"],
            succeeded=False,
        )

        assert balance_for(provider).total == net_for(GROSS)

    def test_a_voided_withdrawal_is_kept_but_not_counted(self):
        provider = shop()
        withdrawal = self._requested(provider)
        settle_transfer(
            provider,
            reference=withdrawal["reference"],
            transfer_id=withdrawal["transfer_id"],
            succeeded=False,
        )

        # The row stays: it is the record that we asked a bank to pay out.
        from payments.models import LedgerEntry

        assert LedgerEntry.objects.filter(
            provider=provider, status=LedgerEntry.Status.VOIDED
        ).exists()

    def test_settling_an_unknown_transfer_is_logged_not_crashed(self):
        provider = shop()

        settle_transfer(provider, reference="nope", transfer_id="x", succeeded=True)

        assert balance_for(provider).total == 0


# ---------------------------------------------------------------------------
# The endpoints
# ---------------------------------------------------------------------------


class TestBalanceEndpoint:
    def test_shows_a_provider_their_position(self):
        provider = shop()
        credit_earning(provider, gross=20000, booking_reference="BK-1")
        client, token = logged_in(provider.user)

        body = client.get(f"{PROVIDERS}me/balance/", **auth_header(token)).data

        assert body["pending"] == net_for(GROSS)
        assert body["pending_display"] == "₹198.00"
        assert body["total_display"] == "₹198.00"

    def test_a_customer_has_no_balance(self):
        client, token = logged_in(make_user())

        assert client.get(f"{PROVIDERS}me/balance/", **auth_header(token)).status_code == 403

    def test_the_ledger_is_listed_newest_first_and_paginated(self):
        provider = shop()
        for index in range(5):
            credit_earning(provider, gross=20000, booking_reference=f"BK-{index}")
        client, token = logged_in(provider.user)

        body = client.get(f"{PROVIDERS}me/ledger/?page_size=3", **auth_header(token)).data

        assert body["count"] == 10  # an earning and a fee line each
        assert len(body["results"]) == 3

    def test_the_ledger_explains_each_line(self):
        provider = shop()
        credit_earning(provider, gross=20000, booking_reference="BK-1")
        client, token = logged_in(provider.user)

        rows = client.get(f"{PROVIDERS}me/ledger/", **auth_header(token)).data["results"]

        assert any(row["description"] == "Booking BK-1" for row in rows)


def make_provider_user():
    from tests.factories import make_provider_user as _make

    return _make()
