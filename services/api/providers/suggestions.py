"""Symptom and intent matching, as a retrieval problem.

A customer says "I want it shorter but not shaved" and needs to be shown the
services that do that. Keyword search cannot do it: the customer's words are
not the shop's words, and the gap between them is the whole problem.

The design constraint from [0005](../../docs/decisions/0005-what-ai-is-for.md)
is that the model is only ever allowed to *choose from a list the backend
supplied*. It cannot invent a price, name a shop that is closed, or change a
booking. So the model is given candidate ids and returns a subset. A model
that hallucinates returns ids that were not on the list, and those are
discarded.

That means the worst outcome of getting this wrong is suggestions that are not
relevant — which costs nothing. A chatbot that gets a cancellation wrong costs
a real appointment.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

#: How long to wait. A search box that takes four seconds to answer feels
#: broken, so the ceiling is deliberately tight and the fallback is instant.
REQUEST_TIMEOUT_SECONDS = 4

#: How many candidates to put in front of the model. More than this and the
#: prompt gets long enough to cost real money per keystroke.
MAX_CANDIDATES = 40


class SuggestionUnavailable(Exception):
    """No model is configured, or it could not be reached."""


class Matcher:
    """Turns free text into a ranked subset of candidate ids."""

    def __init__(self, *, model: str = "", api_key: str = "", endpoint: str = ""):
        self.model = model or settings.AI_MODEL
        self.api_key = api_key or settings.AI_API_KEY
        self.endpoint = endpoint or settings.AI_ENDPOINT

    @property
    def is_configured(self) -> bool:
        return bool(self.model and self.api_key and self.endpoint)

    def rank(self, query: str, candidates: list[dict], *, limit: int = 5) -> list[int]:
        """Ids from ``candidates`` that match ``query``, best first.

        Returns the original order rather than the model's, for anything the
        model did not re-rank. A stable result is better than a clever one when
        the difference is not visible.
        """
        if not candidates or not query.strip():
            return []
        if not self.is_configured:
            raise SuggestionUnavailable("No AI provider is configured.")

        offered = [candidate["id"] for candidate in candidates]
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 200,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You match what a customer wants to a list of options. "
                        "Reply with a JSON array of the option ids that fit, best first. "
                        "Only use ids from the list. If none fit, reply []. "
                        "Never write anything except the array."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "customer_says": query,
                            "options": candidates,
                        }
                    ),
                },
            ],
        }

        try:
            response = requests.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except Exception:
            # Never let a suggestion feature take a search box down with it.
            logger.exception("Could not rank suggestions")
            raise SuggestionUnavailable("The suggestion model did not answer.") from None

        return self._ids_from(content, offered, limit)

    def _ids_from(self, content: str, offered: list[int], limit: int) -> list[int]:
        """Pull ids out of the reply and keep only the ones we offered.

        Models fence JSON, wrap it in prose and trail a comma no matter how
        precisely they are asked, so this looks for the bracketed region rather
        than parsing strictly. What it will *not* do is accept an id that was
        not on the list.
        """
        match = re.search(r"\[([^\]]*)\]", content)
        if match is None:
            logger.info("Model reply contained no array: %r", content[:80])
            return []

        body = re.sub(r"[^0-9,]", "", match.group(1))
        if not body:
            return []

        allowed = set(offered)
        seen: set[int] = set()
        ranked: list[int] = []
        for part in body.split(","):
            if not part:
                continue
            try:
                value = int(part)
            except ValueError:
                continue
            if value in allowed and value not in seen:
                seen.add(value)
                ranked.append(value)
            if len(ranked) >= limit:
                break
        return ranked


def keyword_fallback(query: str, candidates: list[dict], *, limit: int = 5) -> list[int]:
    """What we do when there is no model: plain word matching.

    Worse than the model, and the reason the feature is not a hard dependency.
    Deliberately simple rather than clever — matching on words the shop itself
    wrote is a reasonable thing to do with no budget.
    """
    terms = {word for word in re.findall(r"[a-z0-9]+", query.lower()) if len(word) > 2}
    if not terms:
        return []

    scored: list[tuple[int, int]] = []
    for position, candidate in enumerate(candidates):
        haystack = " ".join(
            str(candidate.get(field, ""))
            for field in ("name", "description", "brand", "service_type")
        ).lower()
        hits = sum(1 for term in terms if term in haystack)
        if hits:
            # Earlier candidates win ties, so the order the shop chose is kept.
            scored.append((-hits, position))

    scored.sort()
    return [candidates[position]["id"] for _hits, position in scored[:limit]]


def service_candidates(services, *, provider=None) -> list[dict]:
    """Build the option list from real, active, purchasable services."""
    options = [
        {
            "id": service.id,
            "name": service.name,
            "description": service.description[:200],
            "duration_minutes": service.duration_minutes,
            "price_display": service.price_display,
        }
        # A retired service stays on old bookings but cannot be booked. Putting
        # one in front of a customer is a dead end they would have to discover.
        for service in services
        if service.is_active
    ]
    return options[:MAX_CANDIDATES]


def provider_candidates(providers) -> list[dict]:
    """Build the option list from shops that can actually be booked.

    A closed shop is not a suggestion. Sending the model a shop that is not
    taking bookings and having it rank first is the kind of thing that costs a
    customer a wasted trip.
    """
    options = [
        {
            "id": provider.id,
            "name": provider.display_name,
            "description": provider.description[:200],
            "service_type": provider.get_service_type_display(),
            "rating": float(provider.rating_average or 0),
        }
        for provider in providers
        if provider.is_bookable
    ]
    return options[:MAX_CANDIDATES]
