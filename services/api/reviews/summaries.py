"""Condensing reviews into something readable.

A shop with sixty reviews has no homepage space for sixty reviews, and a
customer reading the three most recent gets a poor picture of a shop that has
been open for two years.

The summary is about the platform's own merchants, in their own words, with a
verifiable source for every claim. A merchant who thinks it is unfair can read
the reviews it was drawn from.

Like the suggestion matcher, the failure is containment rather than prevention:
a bad summary is a wrong sentence on a shop page, and the reviews underneath
are still there.
"""

from __future__ import annotations

import json
import logging
from collections import Counter

import requests
from django.conf import settings
from django.db.models import Avg, Count

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 4

#: Below this, a "summary" is just the reviews again with extra steps.
MIN_REVIEWS_TO_SUMMARISE = 5

#: Only the most recent are used. Fifty reviews from four years ago describe a
#: shop that may no longer exist, and the barbers have probably moved on.
RECENT_REVIEW_LIMIT = 40


def rating_breakdown(reviews) -> dict:
    """The distribution, computed rather than guessed.

    The average is the number a merchant will argue with and the distribution
    is the number that settles it: a 3.8 from two five-star reviews and three
    one-star ones is a different shop from a steady 3.8.
    """
    counts = Counter(review.rating for review in reviews)
    total = len(reviews)
    # Weighted by how many reviews carry each rating, not a sum of the counts:
    # summing `Counter.values()` adds up "how many fives" rather than the fives.
    total_points = sum(rating * count for rating, count in counts.items())
    return {
        "total": total,
        "average": round(total_points / total, 2) if total else None,
        "distribution": {str(star): counts.get(star, 0) for star in (5, 4, 3, 2, 1)},
    }


def summarise_provider(provider) -> dict:
    """A shop's rating picture, with a written summary when there is enough to say."""
    stats = provider.reviews.aggregate(
        average=Avg("rating"),
        total=Count("id"),
    )
    total = stats["total"] or 0

    payload: dict = {
        "provider": provider.id,
        "total_reviews": total,
        "average": round(float(stats["average"]), 2) if stats["average"] is not None else None,
        "summary": None,
        "summary_source": None,
        "highlights": [],
        "from": [],
    }

    if total == 0:
        payload["summary"] = "No reviews yet."
        return payload

    recent = list(
        provider.reviews.select_related("customer").order_by("-created_at")[:RECENT_REVIEW_LIMIT]
    )
    payload["rating_breakdown"] = rating_breakdown(recent)

    if total < MIN_REVIEWS_TO_SUMMARISE:
        # Two reviews are anecdotes. Say so rather than compressing them into
        # a sentence that sounds like a verdict.
        payload["summary"] = f"{total} review{'s' if total != 1 else ''} so far."
        payload["summary_source"] = "too-few-reviews"
        return payload

    written = _write_summary(provider, recent)
    if written is None:
        # The rating picture is still useful without a sentence, and a shop
        # page with no summary should not be broken because of it.
        payload["summary"] = f"{total} reviews, averaging {payload['average']}."
        payload["summary_source"] = "rating-only"
        return payload

    payload["summary"] = written["summary"]
    payload["highlights"] = written["highlights"]
    payload["summary_source"] = "model"
    # The reviews the summary was drawn from, so a merchant can check it.
    payload["from"] = [review.id for review in recent[:5]]
    return payload


def _write_summary(provider, reviews) -> dict | None:
    """Ask the model for a summary, or return None to fall back."""
    model = settings.AI_MODEL
    api_key = settings.AI_API_KEY
    endpoint = settings.AI_ENDPOINT
    if not (model and api_key and endpoint):
        return None

    body = [{"rating": review.rating, "text": (review.comment or "")[:300]} for review in reviews]

    try:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "max_tokens": 200,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Summarise customer reviews of one hair salon. Reply with JSON: "
                            '{"summary": one sentence, "highlights": up to three short '
                            "phrases}. Describe only what the reviews say. Do not invent "
                            "anything, do not praise the shop, and do not name anyone."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps({"shop": provider.display_name, "reviews": body}),
                    },
                ],
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except Exception:
        logger.exception("Could not summarise reviews for %s", provider.display_name)
        return None

    return _parse(content)


def _parse(content: str) -> dict | None:
    """Pull the summary out, or None if the reply is not the shape we asked for.

    A malformed reply is not an error worth a 500: the caller falls back to the
    rating picture, which is always available.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        parsed = json.loads(text)
    except (ValueError, AttributeError):
        logger.warning("Model returned something that was not JSON")
        return None

    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None

    highlights = parsed.get("highlights")
    if not isinstance(highlights, list):
        highlights = []

    return {
        "summary": summary.strip()[:300],
        "highlights": [str(item).strip()[:80] for item in highlights[:3] if str(item).strip()],
    }
