"""Human-facing references.

A customer reads these out on the phone, so they need two properties: they must
be short enough to say in one breath, and they must not be guessable. Sequential
ids (``BK-1``, ``BK-2``) fail the second badly — they hand over the entire
order history to anyone who opens the app.

The alphabet excludes I, O, 0 and 1. Those are the characters people mishear:
"BK-1BOB1" read aloud is two different references depending on who is saying it.
"""

from __future__ import annotations

import secrets

#: No I/O/0/1.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

LENGTH = 6

#: Prefixes are two letters and are what a customer reads first, so they are
#: part of the interface rather than a detail.
BOOKING = "BK"
ORDER = "OR"


def generate_reference(prefix: str = BOOKING, length: int = LENGTH) -> str:
    """A short, unguessable, unambiguous reference, e.g. ``BK-7QK4M2``."""
    body = "".join(secrets.choice(ALPHABET) for _ in range(length))
    return f"{prefix}-{body}"


def generate_booking_reference() -> str:
    return generate_reference(BOOKING)


def generate_order_reference() -> str:
    return generate_reference(ORDER)
