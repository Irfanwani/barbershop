"""Keys that let something other than the app talk to this API.

A POS integration or an owner's dashboard cannot log in as a person without
either impersonating a user or asking every user for their password. Both are
worse than a key, so the key is the thing that makes the platform embeddable.

Three decisions worth stating up front, because they are the ones people get
wrong:

- **The key is hashed at rest.** We store a lookup prefix and a SHA-256 of the
  whole key. A database dump does not hand anybody the ability to act as a
  customer. Plaintext keys in a table are a breach that survives the breach.
- **A key is scoped to an owner.** It acts *as that user*, never as itself:
  there is no "the API" identity that can read everybody. A leaked key reads
  one customer's bookings, which is a bad day rather than a catastrophe.
- **Revocation is immediate.** The lookup is a hash comparison against live
  rows, so revoking is deleting or flipping a flag - not waiting for a cache,
  a session or a token to expire.
"""

from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel

#: Shown in the UI and on the key's own list so a person can tell two keys
#: apart. Not secret - the part after the prefix is.
PREFIX_LENGTH = 8

#: Enough entropy that guessing is hopeless, short enough to paste into a
#: config file.
SECRET_BYTES = 24


class ApiKey(TimeStampedModel):
    """One key, belonging to one account."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_keys"
    )

    #: A human name. "Till till 2", "Shopfront dashboard".
    name = models.CharField(max_length=80)

    #: Shown in the UI so a person can tell keys apart. Not secret.
    prefix = models.CharField(max_length=16, db_index=True)

    #: SHA-256 of the secret part, hex. The secret itself is shown once at
    #: creation and never again.
    hashed_secret = models.CharField(max_length=64)

    scopes = models.JSONField(
        default=list,
        blank=True,
        help_text="What this key may do. An empty list means nothing.",
    )

    #: Revocation is a flag rather than a delete so the row - and therefore the
    #: usage history - survives the moment somebody decides to stop trusting
    #: something.
    is_active = models.BooleanField(default=True)

    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_api_key"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_active"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…)"

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def usable(self) -> bool:
        return self.is_active and not self.is_expired

    @classmethod
    def issue(cls, *, user, name: str, scopes: list[str], expires_at=None) -> tuple[ApiKey, str]:
        """Create a key, returning the row and the secret.

        The secret is returned exactly once, here. There is no way to recover
        it afterwards, because there is nothing to recover it from - and a
        system that can show you an existing key is a system whose database is
        one dump away from being a credential store.
        """
        prefix = secrets.token_hex(4)[:PREFIX_LENGTH]
        secret = secrets.token_urlsafe(SECRET_BYTES)
        full = f"{prefix}.{secret}"

        key = cls.objects.create(
            user=user,
            name=name,
            prefix=prefix,
            hashed_secret=hash_key(full),
            scopes=sorted(set(scopes)),
            expires_at=expires_at,
        )
        return key, full

    def matches(self, presented: str) -> bool:
        """Whether this is the right key.

        Compared with ``compare_digest`` so a caller cannot learn the hash one
        byte at a time, and the whole presented value is hashed first so a
        caller cannot vary the prefix and learn anything either.
        """
        return secrets.compare_digest(self.hashed_secret, hash_key(presented))

    def has_scope(self, required: str) -> bool:
        return required in self.scopes

    def note_used(self) -> None:
        """Record that this key just worked.

        Updated on a schedule rather than on every request: a counter that
        writes a row per API call is a write amplification problem on the
        busiest key, and the number is only ever read by a person deciding
        whether a key is still needed.
        """
        self.last_used_at = timezone.now()
        type(self).objects.filter(pk=self.pk).update(last_used_at=self.last_used_at)


def hash_key(full_key: str) -> str:
    """The stored form of a key.

    Salted with the deployment's secret, so a stolen database cannot be
    attacked with a precomputed table of hashes even if somebody had somehow
    guessed candidate keys.
    """
    salt = settings.API_KEY_SALT
    return hashlib.sha256(f"{salt}:{full_key}".encode()).hexdigest()
