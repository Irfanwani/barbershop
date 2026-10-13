"""Building the actual spreadsheets.

Every salon runs on one. If their data cannot leave our product they will keep
two records, and ours will be the stale one - so this is not a nice-to-have, it
is the thing that decides whether anybody trusts the numbers here.

The acceptance is one sentence: **an export contains every booking in the
period, not just the first page.** That is written into the code rather than
left to a reviewer:

- **No pagination, anywhere.** Each dataset streams straight off the cursor.
  Anything that fetched "the first 100" and then iterated in Python would pass
  a glance at the code and fail a shop with 400 bookings.
- **Dates come from the request, not from a default window.** An export that
  silently means "the last 30 days" when somebody asked for a year is the kind
  of thing that gets discovered in a tax return.
- **Money is an integer of paise with a formatted column beside it.** A
  spreadsheet that opens in a locale where the decimal separator is a comma
  turns a column of rupees into one enormous number.
- **Free text cannot become a formula.** A booking note typed as ``=cmd()`` must
  not turn into a formula in somebody's spreadsheet. See :func:`_cell`.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

from core.money import format_minor

#: A hard ceiling so one request cannot build a file that fills the disk. At
#: this many rows the shop has a data problem, and the right answer is to talk
#: to them rather than to send them a 4GB attachment.
MAX_ROWS = 250_000

BOOKINGS = "bookings"
REVENUE = "revenue"
CLIENTS = "clients"
PAYOUTS = "payouts"

ALL_DATASETS = [BOOKINGS, REVENUE, CLIENTS, PAYOUTS]


class ExportTooLarge(Exception):
    """Refused rather than attempted."""


@dataclass(frozen=True)
class ExportFile:
    """One CSV, ready to attach."""

    filename: str
    content: bytes
    row_count: int


# ---------------------------------------------------------------------------
# Escaping
# ---------------------------------------------------------------------------


def _cell(value) -> str:
    """One CSV cell.

    A booking note is free text somebody typed into a phone. If it starts with
    ``=``, ``+``, ``-`` or ``@`` then Excel and LibreOffice will treat it as a
    formula and, depending on the version, may try to follow a link in it.
    Prefixing with an apostrophe marks it as text, and Excel hides the
    apostrophe when the cell is read.

    Nothing else needs escaping - :mod:`csv` handles commas, quotes and
    newlines - so this is the whole of the formula problem.
    """
    if value is None:
        return ""
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _to_csv(filename: str, header: list[str], rows: Iterator[list]) -> ExportFile:
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow([_cell(column) for column in header])
    count = 0
    for row in rows:
        count += 1
        if count > MAX_ROWS:
            raise ExportTooLarge(
                f"This export would run to more than {MAX_ROWS:,} rows. "
                "Try a shorter period, or ask us for a bigger file."
            )
        writer.writerow([_cell(value) for value in row])
    # utf-8-sig: Excel on Windows guesses the encoding otherwise and renders
    # every non-ASCII name as mojibake.
    return ExportFile(
        filename=filename, content=buffer.getvalue().encode("utf-8-sig"), row_count=count
    )


# ---------------------------------------------------------------------------
# The datasets
# ---------------------------------------------------------------------------


def bookings(provider, from_date: date, to_date: date) -> ExportFile:
    """Every booking in the period.

    The filter is on ``starts_at``, which is what a salon means by "the
    appointments in March": a booking made in March for April belongs to April.

    ``.iterator()`` rather than a list, because building the list first is what
    turns a spreadsheet into an outage the moment a shop gets busy.
    """
    from bookings.models import Booking

    def build() -> Iterator[list]:
        rows = (
            Booking.objects.filter(
                provider=provider,
                starts_at__date__gte=from_date,
                starts_at__date__lte=to_date,
            )
            .select_related("customer", "staff")
            .order_by("starts_at")
            .iterator(chunk_size=2000)
        )
        for booking in rows:
            yield [
                booking.reference,
                booking.starts_at.isoformat(),
                booking.ends_at.isoformat(),
                # The shop's own clock, which is not what the UTC column shows.
                provider.localtime(booking.starts_at).strftime("%Y-%m-%d %H:%M"),
                booking.get_status_display(),
                booking.customer.display_name,
                booking.customer.phone,
                ", ".join(item.name for item in booking.items.all()),
                booking.subtotal,
                booking.platform_fee,
                booking.total,
                format_minor(booking.subtotal, booking.currency),
                booking.deposit,
                booking.balance,
                booking.amount_paid,
                booking.amount_due,
                booking.staff.name if booking.staff else "",
                # One line per row: a newline inside a cell makes some
                # spreadsheets treat the rest of it as a new record.
                (booking.notes or "").replace("\r", " ").replace("\n", " "),
            ]

    return _to_csv(
        "bookings.csv",
        [
            "reference",
            "starts_at_utc",
            "ends_at_utc",
            "starts_at_local",
            "status",
            "customer",
            "phone",
            "services",
            "subtotal_minor",
            "platform_fee_minor",
            "total_minor",
            "subtotal",
            "deposit_minor",
            "balance_minor",
            "amount_paid_minor",
            "amount_due_minor",
            "staff",
            "notes",
        ],
        build(),
    )


def revenue(provider, from_date: date, to_date: date) -> ExportFile:
    """What was earned and paid out, straight off the ledger.

    Not recomputed from bookings: an export that disagrees with the provider's
    own balance page is the thing that makes them stop trusting both.
    """
    from payments.models import LedgerEntry

    def build() -> Iterator[list]:
        rows = (
            LedgerEntry.objects.filter(
                provider=provider,
                created_at__date__gte=from_date,
                created_at__date__lte=to_date,
            )
            .order_by("created_at", "id")
            .iterator(chunk_size=2000)
        )
        for entry in rows:
            yield [
                entry.created_at.isoformat(),
                entry.kind,
                entry.status,
                entry.amount,
                format_minor(entry.amount),
                entry.reference or "",
                entry.description or "",
            ]

    return _to_csv(
        "revenue.csv",
        [
            "created_at",
            "kind",
            "status",
            "amount_minor",
            "amount",
            "booking_reference",
            "description",
        ],
        build(),
    )


def clients(provider, from_date: date, to_date: date) -> ExportFile:
    """One row per customer, with their counts.

    Aggregated in the database: the set of customers is exactly the large thing
    and the output is exactly the small one.
    """
    from django.db.models import Count, Q

    from bookings.models import Booking

    def build() -> Iterator[list]:
        rows = (
            Booking.objects.filter(
                provider=provider,
                starts_at__date__gte=from_date,
                starts_at__date__lte=to_date,
            )
            .values(
                "customer_id",
                # `display_name` is a property, not a column, so it cannot be
                # selected here. The name is resolved in Python instead - it is
                # `get_full_name() or username`, the same thing the rest of the
                # product shows.
                "customer__first_name",
                "customer__last_name",
                "customer__username",
                "customer__phone",
                "customer__email",
            )
            .annotate(
                bookings=Count("pk"),
                completed=Count("pk", filter=Q(status="completed")),
                no_shows=Count("pk", filter=Q(status="no_show")),
                cancelled=Count("pk", filter=Q(status="cancelled_by_customer")),
            )
            .order_by("customer_id")
            .iterator(chunk_size=2000)
        )
        for row in rows:
            full_name = f"{row['customer__first_name']} {row['customer__last_name']}".strip()
            yield [
                row["customer_id"],
                full_name or row["customer__username"],
                row["customer__phone"] or "",
                row["customer__email"] or "",
                row["bookings"],
                row["completed"],
                row["no_shows"],
                row["cancelled"],
            ]

    return _to_csv(
        "clients.csv",
        [
            "customer_id",
            "name",
            "phone",
            "email",
            "bookings",
            "completed",
            "no_shows",
            "cancelled",
        ],
        build(),
    )


def payouts(provider, from_date: date, to_date: date) -> ExportFile:
    """Everything that has left the balance, and when.

    Payouts are ledger entries rather than rows of their own - the balance page
    is derived from this same table - so an export that read them from somewhere
    else would be the one place the two disagreed.
    """
    from payments.models import LedgerEntry

    def build() -> Iterator[list]:
        rows = (
            LedgerEntry.objects.filter(
                provider=provider,
                kind="paid_out",
                created_at__date__gte=from_date,
                created_at__date__lte=to_date,
            )
            .order_by("created_at", "id")
            .iterator(chunk_size=500)
        )
        for entry in rows:
            yield [
                entry.created_at.isoformat(),
                entry.status,
                # Signed as stored, so the column sums to what left the balance
                # rather than needing the reader to remember the sign.
                -entry.amount,
                format_minor(-entry.amount),
                entry.reference or "",
                entry.description or "",
            ]

    return _to_csv(
        "payouts.csv",
        ["created_at", "status", "paid_out_minor", "paid_out", "reference", "description"],
        build(),
    )


BUILDERS = {
    BOOKINGS: bookings,
    REVENUE: revenue,
    CLIENTS: clients,
    PAYOUTS: payouts,
}


def build(provider, from_date: date, to_date: date, datasets: list[str]) -> list[ExportFile]:
    """Build every requested dataset.

    The size check happens before anything is emailed, so a request that cannot
    be satisfied in full never arrives as a partial file that looks complete.
    """
    chosen = [name for name in ALL_DATASETS if name in set(datasets)]
    if not chosen:
        chosen = list(ALL_DATASETS)
    return [BUILDERS[name](provider, from_date, to_date) for name in chosen]
