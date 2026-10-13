"""Spreadsheet exports.

Every salon runs on one. If their data cannot leave our product they will keep
two records, and ours will be the stale one.

The acceptance is one sentence — **an export contains every booking in the
period, not just the first page** — so the tests are weighted towards the thing
that would quietly get it wrong: anything that paginates. A year-long export
that quietly returns the newest 100 rows passes a glance at the code and fails
the shop that asked for it.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from django.core import mail
from django.utils import timezone

from bookings.models import Booking, BookingStatus
from exports import csv, tasks
from exports.models import ExportRequest, ExportStatus
from payments.ledger import credit_earning
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
EXPORTS = f"{V1}/exports/"

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def a_shop() -> Any:
    owner = make_provider_user(_next_name("shop"))
    owner.email = f"{_next_name('shop')}@example.com"
    owner.save(update_fields=["email"])
    return make_profile(owner, display_name="Sharp Cuts Studio")


def a_period() -> tuple[date, date]:
    today = timezone.localtime().date()
    return today - timedelta(days=30), today


def a_customer(first_name: str | None = None):
    """A customer. `display_name` is derived, so a name is set on the parts."""
    user = make_user(_next_name("cust"))
    if first_name:
        user.first_name = first_name
        user.last_name = "Test"
        user.save(update_fields=["first_name", "last_name"])
    return user


def a_booking(
    provider, customer, *, days_ago: int = 5, status=BookingStatus.COMPLETED, notes: str = ""
):
    from bookings.models import BookingItem

    starts_at = timezone.now() - timedelta(days=days_ago)
    service = make_service(provider, name=f"Service-{_next_name('s')}", price=20000)
    booking = Booking.objects.create(
        customer=customer,
        provider=provider,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        status=status,
        subtotal=service.price,
        platform_fee=service.price // 100,
        total=service.price + service.price // 100,
        deposit=service.price // 2,
        balance=service.price // 2,
        notes=notes,
    )
    BookingItem.objects.create(
        booking=booking,
        service=service,
        name=service.name,
        unit_price=service.price,
        quantity=1,
        duration_minutes=service.duration_minutes,
    )
    if status == BookingStatus.COMPLETED:
        credit_earning(provider, gross=service.price, booking_reference=booking.reference)
    return booking


def parse(content: bytes) -> list[list[str]]:
    import csv as csv_module

    text = content.decode("utf-8-sig")
    return list(csv_module.reader(text.splitlines()))


class TestEveryBookingNotJustTheFirstPage:
    def test_more_rows_than_a_page_come_back(self):
        """The acceptance criterion, stated as a number.

        Anything that fetches a page and iterates in Python passes a glance at
        the code and fails a shop with 400 bookings.
        """
        profile = a_shop()
        customer = a_customer()
        for index in range(250):
            a_booking(profile, customer, days_ago=index % 28 + 1)
        from_date, to_date = a_period()

        result = csv.bookings(profile, from_date, to_date)

        rows = parse(result.content)
        assert result.row_count == 250
        assert len(rows) == 251  # header plus the bookings

    def test_and_every_reference_is_a_distinct_one(self):
        profile = a_shop()
        customer = a_customer()
        for index in range(120):
            a_booking(profile, customer, days_ago=index % 28 + 1)
        from_date, to_date = a_period()

        rows = parse(csv.bookings(profile, from_date, to_date).content)
        references = [row[0] for row in rows[1:]]

        assert len(references) == len(set(references))
        assert set(references) == set(
            Booking.objects.filter(provider=profile).values_list("reference", flat=True)
        )

    def test_bookings_outside_the_period_are_left_out(self):
        profile = a_shop()
        customer = a_customer()
        a_booking(profile, customer, days_ago=5)
        a_booking(profile, customer, days_ago=200)

        today = timezone.localtime().date()
        result = csv.bookings(profile, today - timedelta(days=30), today)

        assert result.row_count == 1

    def test_another_shops_bookings_are_never_included(self):
        mine = a_shop()
        theirs = a_shop()
        customer = a_customer()
        a_booking(mine, customer, days_ago=3)
        a_booking(theirs, a_customer(), days_ago=3)
        from_date, to_date = a_period()

        result = csv.bookings(mine, from_date, to_date)

        assert result.row_count == 1


class TestTheMoneyIsRight:
    def test_paise_and_a_readable_amount(self):
        """A spreadsheet that opens where the decimal separator is a comma turns
        a column of rupees into one enormous number."""
        profile = a_shop()
        a_booking(profile, a_customer(), days_ago=2)
        from_date, to_date = a_period()

        rows = parse(csv.bookings(profile, from_date, to_date).content)
        header, booking = rows[0], rows[1]

        assert header[header.index("subtotal_minor")] == "subtotal_minor"
        assert booking[header.index("subtotal_minor")] == "20000"
        assert booking[header.index("subtotal")].startswith("₹200")

    def test_revenue_comes_from_the_ledger(self):
        """An export that disagrees with the provider's own balance page is the
        thing that makes them stop trusting both."""
        profile = a_shop()
        a_booking(profile, a_customer(), days_ago=2)
        from_date, to_date = a_period()

        result = csv.revenue(profile, from_date, to_date)

        assert result.row_count >= 1
        rows = parse(result.content)
        assert "kind" in rows[0]
        assert any(row[rows[0].index("kind")] == "earning" for row in rows[1:])

    def test_payouts_are_reported_as_money_that_left(self):
        """Signed so the column sums to what went, rather than needing the
        reader to remember the sign."""
        from payments.models import LedgerEntry

        profile = a_shop()
        LedgerEntry.objects.create(
            provider=profile,
            kind="earning",
            status="cleared",
            amount=20000,
            reference="BK-1",
        )
        LedgerEntry.objects.create(
            provider=profile,
            kind="paid_out",
            status="paid_out",
            amount=-20000,
            reference="payout-1",
        )
        from_date, to_date = a_period()

        rows = parse(csv.payouts(profile, from_date, to_date).content)
        header = rows[0]
        assert rows[1][header.index("paid_out_minor")] == "20000"
        assert rows[1][header.index("reference")] == "payout-1"


class TestClientsAreAggregated:
    def test_one_row_per_customer(self):
        profile = a_shop()
        regular = a_customer()
        for days in (2, 4, 6):
            a_booking(profile, regular, days_ago=days)
        a_booking(profile, a_customer(), days_ago=3)
        from_date, to_date = a_period()

        result = csv.clients(profile, from_date, to_date)

        assert result.row_count == 2
        rows = parse(result.content)
        header = rows[0]
        counts = {row[header.index("name")]: row[header.index("bookings")] for row in rows[1:]}
        assert counts[regular.display_name] == "3"


class TestTheFileIsSafeToOpen:
    def test_a_note_cannot_become_a_formula(self):
        """Somebody types ``=cmd()`` into a notes box and it lands in a
        spreadsheet that runs it."""
        profile = a_shop()
        a_booking(profile, a_customer(), days_ago=2, notes='=HYPERLINK("http://evil","x")')
        from_date, to_date = a_period()

        rows = parse(csv.bookings(profile, from_date, to_date).content)
        header = rows[0]

        assert rows[1][header.index("notes")].startswith("'=")

    def test_a_newline_in_a_note_does_not_make_a_new_row(self):
        profile = a_shop()
        a_booking(profile, a_customer(), days_ago=2, notes="first line\nsecond line")
        from_date, to_date = a_period()

        rows = parse(csv.bookings(profile, from_date, to_date).content)

        assert len(rows) == 2

    def test_a_comma_or_quote_does_not_break_the_row(self):
        profile = a_shop()
        a_booking(profile, a_customer(), days_ago=2, notes='Trim, please - "not too short"')
        from_date, to_date = a_period()

        rows = parse(csv.bookings(profile, from_date, to_date).content)

        assert len(rows) == 2
        assert 'Trim, please - "not too short"' == rows[1][rows[0].index("notes")]

    def test_it_opens_in_excel_without_mojibake(self):
        """utf-8-sig: Excel on Windows guesses the encoding otherwise."""
        profile = a_shop()
        a_booking(profile, a_customer("José"), days_ago=2)
        from_date, to_date = a_period()

        result = csv.bookings(profile, from_date, to_date)

        assert result.content.startswith(b"\xef\xbb\xbf")


class TestDatesAreTheShopsOwn:
    def test_both_utc_and_local_are_given(self):
        """They are not the same, and the local one is the one they booked."""
        profile = a_shop()
        profile.timezone_name = "Asia/Kolkata"
        profile.save(update_fields=["timezone_name"])
        a_booking(profile, a_customer(), days_ago=2)
        from_date, to_date = a_period()

        rows = parse(csv.bookings(profile, from_date, to_date).content)
        header = rows[0]

        utc = rows[1][header.index("starts_at_utc")]
        local = rows[1][header.index("starts_at_local")]

        assert utc.endswith("+00:00")
        assert local
        assert not local.endswith("+00:00")


class TestTheWholeJob:
    def test_it_builds_every_dataset(self):
        profile = a_shop()
        a_booking(profile, a_customer(), days_ago=2)
        from_date, to_date = a_period()

        files = csv.build(profile, from_date, to_date, csv.ALL_DATASETS)

        assert {item.filename for item in files} == {
            "bookings.csv",
            "revenue.csv",
            "clients.csv",
            "payouts.csv",
        }

    def test_it_can_build_only_what_was_asked_for(self):
        profile = a_shop()
        from_date, to_date = a_period()

        files = csv.build(profile, from_date, to_date, ["bookings"])

        assert [item.filename for item in files] == ["bookings.csv"]

    def test_a_refusal_stops_the_whole_thing(self):
        """Never a partial file that looks complete."""
        from unittest import mock

        profile = a_shop()
        from_date, to_date = a_period()

        with mock.patch.object(csv, "MAX_ROWS", 1):
            with pytest.raises(csv.ExportTooLarge):
                a_booking(profile, a_customer(), days_ago=2)
                csv.build(profile, from_date, to_date, csv.ALL_DATASETS)


class TestTheRequest:
    def test_it_is_queued_and_the_row_comes_back(self):
        profile = a_shop()
        client, token = logged_in(profile.user)
        from_date, to_date = a_period()

        response = client.post(
            EXPORTS,
            {"from_date": from_date.isoformat(), "to_date": to_date.isoformat()},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 202, response.data
        assert response.data["status"] == ExportStatus.QUEUED
        assert ExportRequest.objects.count() == 1

    def test_the_period_is_required(self):
        profile = a_shop()
        client, token = logged_in(profile.user)

        response = client.post(
            EXPORTS,
            {"from_date": "2026-01-01"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_an_end_before_the_start_is_refused(self):
        profile = a_shop()
        client, token = logged_in(profile.user)

        response = client.post(
            EXPORTS,
            {"from_date": "2026-03-01", "to_date": "2026-01-01"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_a_customer_cannot_ask(self):
        client, token = logged_in(make_user(_next_name("cust")))

        response = client.post(
            EXPORTS,
            {"from_date": "2026-01-01", "to_date": "2026-03-01"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code in (403, 404)

    def test_a_shop_cannot_see_another_shops_requests(self):
        mine = a_shop()
        theirs = a_shop()
        row = ExportRequest.objects.create(
            provider=theirs,
            requested_by=theirs.user,
            from_date=date(2026, 1, 1),
            to_date=date(2026, 3, 1),
            datasets=list(csv.ALL_DATASETS),
        )
        client, token = logged_in(mine.user)

        response = client.get(f"{EXPORTS}{row.pk}/", **auth_header(token))

        assert response.status_code == 404


class TestSendingIt:
    def test_the_files_arrive_as_attachments(self, monkeypatch):
        profile = a_shop()
        owner = profile.user
        owner.email = "shop@example.com"
        owner.save(update_fields=["email"])
        customer = a_customer()
        for days in (2, 4, 6):
            a_booking(profile, customer, days_ago=days)

        row = ExportRequest.objects.create(
            provider=profile,
            requested_by=owner,
            from_date=a_period()[0],
            to_date=a_period()[1],
            datasets=["bookings"],
        )

        _run_export_sync(row)

        row.refresh_from_db()
        assert row.status == ExportStatus.SENT
        assert row.row_count == 3

        assert len(mail.outbox) == 1
        sent = mail.outbox[0]
        assert sent.to == ["shop@example.com"]
        assert [part[0] for part in sent.attachments] == ["bookings.csv"]

    def test_running_it_twice_does_not_email_twice(self):
        """The task can be redelivered. Sending twice is the one thing that must
        never happen here."""
        profile = a_shop()
        profile.user.email = "shop@example.com"
        profile.user.save(update_fields=["email"])
        row = ExportRequest.objects.create(
            provider=profile,
            requested_by=profile.user,
            from_date=a_period()[0],
            to_date=a_period()[1],
            datasets=["bookings"],
        )

        _run_export_sync(row)
        _run_export_sync(row)

        assert len(mail.outbox) == 1

    def test_a_failure_is_recorded_rather_than_being_swallowed(self):
        """Otherwise 'the export never came' is unactionable."""
        profile = a_shop()
        profile.user.email = "shop@example.com"
        profile.user.save(update_fields=["email"])
        row = ExportRequest.objects.create(
            provider=profile,
            requested_by=profile.user,
            from_date=a_period()[0],
            to_date=a_period()[1],
            datasets=["bookings"],
        )

        from unittest import mock

        with mock.patch("exports.email.send_export", return_value=False):
            _run_export_sync(row)

        row.refresh_from_db()
        assert row.status == ExportStatus.FAILED
        assert row.failure_reason

    def test_a_refusal_does_not_email_anything(self):
        from unittest import mock

        profile = a_shop()
        profile.user.email = "shop@example.com"
        profile.user.save(update_fields=["email"])
        a_booking(profile, a_customer(), days_ago=2)
        row = ExportRequest.objects.create(
            provider=profile,
            requested_by=profile.user,
            from_date=a_period()[0],
            to_date=a_period()[1],
            datasets=["bookings"],
        )

        with mock.patch.object(csv, "MAX_ROWS", 0):
            _run_export_sync(row)

        row.refresh_from_db()
        assert row.status == ExportStatus.FAILED
        assert not mail.outbox


def _run_export_sync(row: ExportRequest) -> None:
    """Run the real task, without a broker.

    ``apply()`` executes the task body itself rather than a copy of it, so this
    tests the shipped code path - including the "already sent" guard that a
    re-implementation would quietly omit.
    """
    tasks.run_export.apply(args=(row.pk,)).get()
