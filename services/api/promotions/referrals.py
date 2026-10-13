"""Give a credit, get a credit.

The category standard, and the reason it is fussier than it looks: **a referral
programme is a way to mint points**, so every rule here is about closing a hole
rather than about generosity.

The holes, and what closes each:

- **Paying for self-referrals.** Enforced by a check constraint on the table, so
  no endpoint written in a hurry can forget it.
- **Paying more than once per person.** ``referred`` is unique. A customer has
  one referrer for life.
- **Paying at booking time.** The reward waits for the referred customer's
  **first completed** booking. A booking can be cancelled, rescheduled into next
  month, or turn into a no-show, and a reward for an appointment that never
  happened is a purchase of points.
- **Paying twice for the same appointment.** ``booking`` is unique and
  ``rewarded_at`` is set once.
- **Crediting the wrong shop.** The provider is recorded from the booking that
  actually completed, not from whoever issued the code. Somebody can hand out
  their code and send the friend somewhere else entirely, and crediting the
  issuing shop would be a lie told in the ledger.

Nothing here touches the money ledger. A referral is worth points, and points
are already the currency the platform has decided to honour.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from promotions.loyalty import award
from promotions.models import Referral, ReferralCode, ReferralStatus

logger = logging.getLogger(__name__)

#: Points to each side when a referral completes. Small on purpose: this buys a
#: haircut for the person who was sent, and it should not out-earn a booking.
REFERRER_POINTS = 100
REFERRED_POINTS = 150

#: Short enough to read out over the phone, short enough not to be guessed.
CODE_LENGTH = 8

#: Alphabet without characters people confuse when reading a code aloud: no
#: zero/O, no one/I.
_ALPHABET = "ACDEFGHJKLMNPQRTUVWXY23456789"


class ReferralRejected(Exception):
    """This referral cannot happen. Carries a message for the customer."""


@dataclass
class ReferralOutcome:
    referral: Referral | None = None
    #: Why nothing happened, for the log and for tests.
    reason: str = ""
    referrer_points: int = 0
    referred_points: int = 0


def code_for(customer) -> ReferralCode:
    """This customer's code, created on first use.

    Lazily rather than on signup: a code for somebody who never refers anybody
    is a row nobody will ever read, and creating it at signup means writing to
    a table on every registration.
    """
    existing = ReferralCode.objects.filter(customer=customer).first()
    if existing is not None:
        return existing

    # A collision on eight characters is unlikely but not impossible, and the
    # unique index is what makes it safe. Retried rather than caught: a code
    # that collided is somebody else's referral code, and handing it out would
    # pay them twice.
    for _attempt in range(8):
        try:
            with transaction.atomic():
                return ReferralCode.objects.create(customer=customer, code=_generate_code())
        except IntegrityError:
            continue
    raise ReferralRejected("Could not make you a referral code. Try again shortly.")


def _generate_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))


def attach(booking, raw_code: str | None) -> Referral | None:
    """Link a booking to the code it was made with.

    Called at booking time, and records nothing but the pending link. The
    credit comes later, from :func:`reward`.
    """
    if not raw_code or not raw_code.strip():
        return None
    candidate = raw_code.strip().upper()

    code_row = ReferralCode.objects.filter(code=candidate).select_related("customer").first()
    if code_row is None:
        # Not an error worth bothering the customer with at the checkout: a
        # mistyped or stale code must not block a booking.
        logger.info("Referral code %s is not one of ours", candidate)
        return None

    referrer = code_row.customer
    if referrer.pk == booking.customer_id:
        # The check constraint would refuse this anyway. Refusing it here with
        # a reason means the log says *why* rather than recording a constraint
        # violation.
        raise ReferralRejected("You cannot use your own referral code.")

    if Referral.objects.filter(referred=booking.customer).exists():
        raise ReferralRejected("You have already been referred by somebody.")

    try:
        with transaction.atomic():
            referral = Referral.objects.create(
                referrer=referrer,
                referred=booking.customer,
                code=code_row,
                # Linked now, not when it is rewarded. This is the booking the
                # code was used on, and it is the only thing that lets a
                # cancellation find the referral and lapse it - a referral with
                # no booking on it is a referral that survives the appointment
                # it was attached to falling over.
                booking=booking,
                # Not set yet. The shop is whoever actually does the work, which
                # is not known until a booking completes.
                provider=None,
                status=ReferralStatus.PENDING,
            )
    except IntegrityError:
        # Two of the referred customer's bookings completing at once, or the
        # same person being referred twice in a race.
        raise ReferralRejected("You have already been referred by somebody.") from None

    logger.info("Referral recorded: %s", referral)
    return referral


def reward(booking) -> ReferralOutcome:
    """Pay out a referral, if this booking is the one that earned it.

    Called on completion, for the same reason points are: a booking can still be
    cancelled or turn into a no-show.
    """
    if booking.customer_id is None:
        return ReferralOutcome(reason="no customer")

    referral = Referral.objects.filter(
        referred=booking.customer, status=ReferralStatus.PENDING
    ).first()
    if referral is None:
        return ReferralOutcome(reason="no pending referral")

    # Only the *first* completed booking counts. Somebody who was referred, did
    # not come for six months, and then came twice in a row has been referred
    # once.
    already = (
        referral.referrer_id == booking.customer_id
        or Referral.objects.filter(
            referred=booking.customer, status=ReferralStatus.REWARDED
        ).exists()
    )
    if already:
        return ReferralOutcome(referral=referral, reason="already rewarded")

    with transaction.atomic():
        locked = Referral.objects.select_for_update().filter(pk=referral.pk).first()
        if locked is None or locked.rewarded_at is not None:
            # Another worker got there first. One appointment pays out once.
            return ReferralOutcome(reason="already rewarded")
        if locked.status != ReferralStatus.PENDING:
            return ReferralOutcome(referral=locked, reason=f"status {locked.status}")

        award(
            locked.referrer,
            points=REFERRER_POINTS,
            reason="referral",
            booking=booking,
            provider=booking.provider,
        )
        award(
            locked.referred,
            points=REFERRED_POINTS,
            reason="referral",
            booking=booking,
            provider=booking.provider,
        )

        locked.status = ReferralStatus.REWARDED
        locked.booking = booking
        # Attributed to the shop that actually did the work, not the shop whose
        # code was used.
        locked.provider = booking.provider
        locked.referrer_points = REFERRER_POINTS
        locked.referred_points = REFERRED_POINTS
        locked.rewarded_at = timezone.now()
        locked.save(
            update_fields=[
                "status",
                "booking",
                "provider",
                "referrer_points",
                "referred_points",
                "rewarded_at",
            ]
        )

    logger.info("Referral rewarded: %s", locked)
    return ReferralOutcome(
        referral=locked,
        referrer_points=REFERRER_POINTS,
        referred_points=REFERRED_POINTS,
    )


def lapse_for_cancelled(booking) -> None:
    """A pending referral whose appointment fell over is not owed anything.

    Marked lapsed rather than deleted, so the customer who was referred is not
    quietly able to be referred again by somebody else after a cancellation.
    """
    Referral.objects.filter(booking=booking, status=ReferralStatus.PENDING).update(
        status=ReferralStatus.LAPSED
    )


def summary_for(customer) -> dict:
    """What to show somebody about their own referrals."""
    given = list(Referral.objects.filter(referrer=customer).select_related("provider")[:20])
    used = Referral.objects.filter(referred=customer).first()
    return {
        "code": code_for(customer).code,
        "given": [
            {
                "referred_display_name": getattr(referral.referred, "display_name", ""),
                "status": referral.status,
                "provider": referral.provider.display_name if referral.provider else None,
                "rewarded_at": referral.rewarded_at,
            }
            for referral in given
        ],
        "given_count": Referral.objects.filter(referrer=customer).count(),
        "rewarded_count": Referral.objects.filter(
            referrer=customer, status=ReferralStatus.REWARDED
        ).count(),
        "referred_by": used.referrer.display_name if used else None,
    }
