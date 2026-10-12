"""Filling a freed slot from the waitlist.

The promise every competitor makes here is "first to reply gets the slot —
filled in seconds". That is only true if two things hold: the right person is
found, and the slot belongs to them while they decide. Both are easy to get
subtly wrong, and neither is visible until a customer is told a slot is theirs
and then finds someone else in the chair.

The rules this file encodes:

- **First come, first served.** Ordered by when the customer joined, not by who
  is a better customer or who last booked.
- **A hold is real.** The offered slot stops being publicly bookable, and a
  decline hands it to the next person rather than dropping it.
- **Lapsing is not declining.** Someone who did not answer is offered the next
  suitable slot; someone who said no is not offered that slot again, but may
  still be waiting for another.
- **Silence never blocks a slot forever.** Every hold has an expiry, and an
  expired hold is treated as no hold even if the cleanup task has not run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from bookings.models import (
    Booking,
    SlotHold,
    WaitlistEntry,
    WaitlistOffer,
    WaitlistStatus,
)
from core.notifications import deliver_push
from providers.models import ProviderProfile, Staff

logger = logging.getLogger(__name__)

#: How long someone has to answer before the slot goes to the next person.
#: Long enough to open a notification and tap through, short enough that the
#: chair is not standing empty.
DEFAULT_HOLD_MINUTES = 15


def hold_minutes() -> int:
    return getattr(settings, "WAITLIST_HOLD_MINUTES", DEFAULT_HOLD_MINUTES)


@dataclass(frozen=True)
class FreedSlot:
    """A slot somebody is no longer using.

    Deliberately not a Booking. The booking a slot came from has been cancelled
    and may be gone by the time a decline needs to hand the slot on, so what the
    waitlist actually needs is the slot itself: whose shop it is, what it is
    for, when, and whose chair it was.
    """

    provider: ProviderProfile
    service_ids: frozenset[int]
    starts_at: datetime
    ends_at: datetime
    staff: Staff | None = None
    vacated_by: int | None = None

    @property
    def shop_name(self) -> str:
        return self.provider.display_name


def slot_from_booking(booking: Booking) -> FreedSlot:
    return FreedSlot(
        provider=booking.provider,
        service_ids=frozenset(
            booking.items.filter(service__isnull=False).values_list("service_id", flat=True)
        ),
        starts_at=booking.starts_at,
        ends_at=booking.ends_at,
        staff=booking.staff,
        vacated_by=booking.customer_id,
    )


def slot_from_offer(offer: WaitlistOffer) -> FreedSlot:
    """The slot an offer is for, reconstructed from the offer itself."""
    return FreedSlot(
        provider=offer.entry.provider,
        service_ids=frozenset({offer.entry.service_id}),
        starts_at=offer.starts_at,
        ends_at=offer.ends_at,
        staff=offer.staff,
    )


def matching_entries(slot: FreedSlot) -> list[WaitlistEntry]:
    """Everyone waiting for exactly this shop, service and moment.

    Ordered by when they joined. A customer who joined before you get the slot
    before you do, which is the entire promise.
    """
    entries = (
        WaitlistEntry.objects.filter(
            provider=slot.provider,
            service_id__in=slot.service_ids,
            status=WaitlistStatus.WAITING,
        )
        .exclude(customer_id=slot.vacated_by)
        .select_related("customer", "staff", "provider")
        .order_by("created_at", "pk")
    )

    # The window and the barber are checked in Python because both depend on
    # the slot's own start and end.
    return [entry for entry in entries if entry.matches(slot) and entry.wants(slot.staff)]


def offer_freed_slot(
    slot: FreedSlot,
    *,
    entries: list[WaitlistEntry] | None = None,
) -> WaitlistOffer | None:
    """Offer a cancelled slot to the first person waiting for it.

    Returns the offer, or None if nobody matches — in which case the slot is
    simply public again, which is the correct outcome and not a failure.
    """
    candidates = entries if entries is not None else matching_entries(slot)

    now = timezone.now()
    expires_at = now + timedelta(minutes=hold_minutes())

    for entry in candidates:
        if _offer_exists(slot, entry):
            # One person cannot be offered the same chair twice, or a shop
            # cancelling three of their bookings at once sends three identical
            # notifications about the same slot.
            continue
        offer = _create_offer(slot, entry, expires_at)
        _notify(entry, slot, offer)
        return offer

    return None


def _offer_exists(slot: FreedSlot, entry: WaitlistEntry) -> bool:
    """Whether this entry has already been offered this exact slot.

    Any status counts, not just a pending one. Otherwise someone who lets an
    offer lapse is put straight back at the front of the queue for the same
    chair: expire, re-offer, expire, re-offer, while the people behind them
    watch an empty chair. One turn each, then it is public again.
    """
    return WaitlistOffer.objects.filter(
        entry=entry,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
    ).exists()


@transaction.atomic
def _create_offer(slot: FreedSlot, entry: WaitlistEntry, expires_at) -> WaitlistOffer:
    offer = WaitlistOffer.objects.create(
        entry=entry,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        staff=slot.staff,
        expires_at=expires_at,
    )
    SlotHold.objects.create(
        offer=offer,
        provider=slot.provider,
        staff=slot.staff,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
    )
    # Moved in the database rather than in memory, so a second cancellation
    # running at the same moment cannot offer the same person the same chair.
    WaitlistEntry.objects.filter(pk=entry.pk, status=WaitlistStatus.WAITING).update(
        status=WaitlistStatus.OFFERED
    )
    entry.status = WaitlistStatus.OFFERED
    return offer


def _notify(entry: WaitlistEntry, slot: FreedSlot, offer: WaitlistOffer) -> None:
    tokens = list(entry.customer.push_tokens.filter(active=True).values_list("token", flat=True))
    if not tokens:
        return
    deliver_push(
        tokens,
        title="A slot just opened",
        body=(
            f"{slot.shop_name} has a free {format_slot_time(slot.starts_at, slot.provider)} — "
            f"yours until {format_slot_time(offer.expires_at, slot.provider)}."
        ),
        data={"screen": "waitlist", "offer_id": offer.pk},
    )


def format_slot_time(moment: datetime, provider=None) -> str:
    """ "3pm" today, "tomorrow 10am" otherwise.

    A bare clock time in a notification is ambiguous the first time someone
    reads it the day after — and "3pm" is only meaningful relative to somebody's
    clock, so this asks the shop's when it knows which shop.
    """
    local = provider.localtime(moment) if provider is not None else timezone.localtime(moment)
    now = provider.local_now() if provider is not None else timezone.localtime()
    clock = local.strftime("%-I%p").lower()
    if local.date() == now.date():
        return f"{clock} today"
    if local.date() == (now + timedelta(days=1)).date():
        return f"{clock} tomorrow"
    return f"{clock} on {local:%a %-d %b}"


class OfferUnavailable(Exception):
    """The offer is gone: declined, expired, or already used."""


@transaction.atomic
def accept_offer(offer: WaitlistOffer) -> Booking:
    """Turn an accepted offer into a real booking.

    Re-runs the full booking rules rather than trusting the offer. A waitlist
    entry can sit for days across a price change or a revised cancellation
    policy, and a booking built from stale assumptions is worse than a refused
    accept.
    """
    from rest_framework.exceptions import ValidationError

    from bookings.serializers import BookingCreateSerializer

    entry = offer.entry

    if offer.status != "pending" or offer.expires_at <= timezone.now():
        raise OfferUnavailable("That offer has expired.")

    # The hold goes first. It exists to stop anyone *else* taking this slot
    # while the customer decides — and it is this customer's own booking being
    # created, which the hold would otherwise refuse as "already taken". Both
    # happen in one transaction, so nothing can slip in between.
    SlotHold.objects.filter(offer=offer).delete()

    payload = {
        "provider": entry.provider_id,
        "services": [entry.service_id],
        "starts_at": offer.starts_at.isoformat(),
    }
    if offer.staff_id:
        payload["staff"] = offer.staff_id

    serializer = BookingCreateSerializer(
        data=payload, context={"request": _request_for(entry.customer)}
    )
    if not serializer.is_valid():
        raise ValidationError(serializer.errors)

    booking = serializer.save()

    offer.status = "accepted"
    offer.save(update_fields=["status", "updated_at"])

    entry.status = WaitlistStatus.BOOKED
    entry.save(update_fields=["status", "updated_at"])

    return booking


@transaction.atomic
def decline_offer(offer: WaitlistOffer) -> WaitlistOffer | None:
    """Release a declined slot to the next person waiting.

    Returns the next offer, or None if nobody is left to take it — in which case
    the slot goes back to being public, which is the honest outcome.
    """
    if offer.status != "pending":
        return None

    offer.status = "declined"
    offer.save(update_fields=["status", "updated_at"])
    SlotHold.objects.filter(offer=offer).delete()

    entry = offer.entry
    # Declining this slot is not leaving the waitlist. They said no to this
    # minute; they may still want the one after it.
    entry.status = WaitlistStatus.WAITING
    entry.save(update_fields=["status", "updated_at"])

    return offer_freed_slot(slot_from_offer(offer))


def expire_offers(now=None) -> dict[str, int]:
    """Return lapsed slots to the public list, re-offering where anyone is left.

    Runs on a schedule, but nothing depends on it having run: every availability
    check treats an expired hold as no hold, so a dead worker costs nothing but
    the next person in line waiting for the next run.
    """
    now = now or timezone.now()
    counts = {"expired": 0, "reoffered": 0}

    lapsed = list(
        WaitlistOffer.objects.filter(status="pending", expires_at__lte=now).select_related(
            "entry__provider", "entry__customer", "entry__service", "staff"
        )
    )

    for offer in lapsed:
        with transaction.atomic():
            offer.status = "expired"
            offer.save(update_fields=["status", "updated_at"])
            SlotHold.objects.filter(offer=offer).delete()

            entry = offer.entry
            entry.status = WaitlistStatus.WAITING
            entry.save(update_fields=["status", "updated_at"])

        counts["expired"] += 1

        # Hand it straight to the next person rather than making them wait for
        # the next run of the task.
        if offer_freed_slot(slot_from_offer(offer)) is not None:
            counts["reoffered"] += 1

    if any(counts.values()):
        logger.info("Waitlist offers expired: %s", counts)
    return counts


@transaction.atomic
def cancel_entry(entry: WaitlistEntry) -> None:
    """Take someone off the waitlist, releasing any slot held for them."""
    for offer in list(entry.offers.filter(status="pending")):
        offer.status = "declined"
        offer.save(update_fields=["status", "updated_at"])
        SlotHold.objects.filter(offer=offer).delete()
        offer_freed_slot(slot_from_offer(offer))

    entry.status = WaitlistStatus.LEFT
    entry.save(update_fields=["status", "updated_at"])


def _request_for(user):
    """A minimal request, so the booking serializer can read the customer."""
    from rest_framework.test import APIRequestFactory

    request = APIRequestFactory().post("/")
    request.user = user
    request.auth = None
    return request
