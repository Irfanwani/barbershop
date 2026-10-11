"""The two AI features, and the properties they must keep.

These tests mostly do not test the model. They test that the model's answer is
*contained*: ids it invents are discarded, a failure falls back rather than
propagating, and with nothing configured the app behaves exactly as it did
before any of this existed.

That is the whole point of the design in `docs/decisions/0005`: a suggestion
feature should be wrong in a way that costs nothing.
"""

from __future__ import annotations

import json

import pytest

from providers import suggestions as suggestions_module
from providers.models import ServiceType
from providers.suggestions import (
    Matcher,
    SuggestionUnavailable,
    keyword_fallback,
    provider_candidates,
    service_candidates,
)
from reviews import summaries as summaries_module
from reviews.models import Review
from reviews.summaries import _parse, rating_breakdown, summarise_provider
from tests.factories import (
    auth_header,
    logged_in,
    make_profile,
    make_service,
    make_user,
)

pytestmark = pytest.mark.django_db

V1 = "/api/v1"


class FakeReview:
    """The smallest thing `rating_breakdown` can read."""

    def __init__(self, rating):
        self.rating = rating


class FakeResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def stub_model(monkeypatch, reply):
    monkeypatch.setattr(suggestions_module.requests, "post", lambda *a, **k: FakeResponse(reply))


def configured_matcher() -> Matcher:
    return Matcher(model="test-model", api_key="key", endpoint="https://example.test/v1")


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


class TestMatcherContainment:
    def test_returns_only_ids_that_were_offered(self):
        # The safety property: a model asked to choose freely will choose
        # freely, so anything not on the list is thrown away.
        matcher = configured_matcher()

        ids = matcher._ids_from("[1, 2, 99999]", [1, 2, 3], limit=5)

        assert ids == [1, 2]

    def test_discards_an_empty_reply(self):
        assert configured_matcher()._ids_from("[]", [1, 2], limit=5) == []

    def test_recovers_from_a_fenced_reply(self):
        # Models fence JSON constantly. Parsing strictly would throw away good
        # answers over formatting.
        matcher = configured_matcher()

        assert matcher._ids_from("```json\n[2, 3]\n```", [1, 2, 3], limit=5) == [2, 3]

    def test_recovers_from_prose_around_the_array(self):
        matcher = configured_matcher()

        assert matcher._ids_from("Sure! [1, 3]", [1, 2, 3], limit=5) == [1, 3]

    def test_does_not_repeat_an_id(self):
        matcher = configured_matcher()

        assert matcher._ids_from("[1, 1, 2, 2]", [1, 2, 3], limit=5) == [1, 2]

    def test_respects_the_limit(self):
        matcher = configured_matcher()

        assert matcher._ids_from("[1, 2, 3, 4, 5, 6]", [1, 2, 3, 4, 5, 6], limit=3) == [1, 2, 3]

    def test_keeps_the_models_ordering(self):
        matcher = configured_matcher()

        # The model knows "blend" and "fade" are both fades and that "facial"
        # is neither; its ranking is the whole value.
        assert matcher._ids_from("[3, 1]", [1, 2, 3], limit=5) == [3, 1]

    def test_discards_a_reply_that_is_not_a_list(self):
        matcher = configured_matcher()

        assert matcher._ids_from("I cannot help with that.", [1, 2], limit=5) == []


class TestMatcherFailure:
    def test_a_model_that_is_not_configured_says_so(self):
        assert Matcher(model="", api_key="", endpoint="").is_configured is False
        with pytest.raises(SuggestionUnavailable):
            Matcher(model="", api_key="", endpoint="").rank("fade", [{"id": 1, "name": "x"}])

    def test_a_dead_endpoint_raises_rather_than_returning_nonsense(self, monkeypatch):
        def boom(*args, **kwargs):
            raise ConnectionError("model service down")

        monkeypatch.setattr(suggestions_module.requests, "post", boom)

        with pytest.raises(SuggestionUnavailable):
            configured_matcher().rank("fade", [{"id": 1, "name": "Fade"}])

    def test_an_empty_query_is_answered_without_the_model(self):
        # Cheaper, and it means an accidental double-tap on search costs nothing.
        assert configured_matcher().rank("   ", [{"id": 1, "name": "Fade"}]) == []

    def test_no_candidates_means_no_call(self):
        assert configured_matcher().rank("fade", []) == []


class TestKeywordFallback:
    """What happens with no model configured — which is the default."""

    def test_matches_a_word_in_the_name(self):
        candidates = [{"id": 1, "name": "Skin fade"}, {"id": 2, "name": "Beard trim"}]

        assert keyword_fallback("I want a skin fade", candidates) == [1]

    def test_matches_a_word_in_the_description(self):
        candidates = [
            {"id": 1, "name": "Service A", "description": "for thinning hair"},
            {"id": 2, "name": "Beard trim", "description": "shaping"},
        ]

        assert keyword_fallback("something for thinning", candidates) == [1]

    def test_ignores_words_too_short_to_mean_anything(self):
        candidates = [{"id": 1, "name": "Beard up"}]

        # "a", "to", "up" match half the dictionary and tell nobody anything.
        assert keyword_fallback("a to it", candidates) == []

    def test_returns_nothing_when_nothing_matches(self):
        assert keyword_fallback("underwater basket weaving", [{"id": 1, "name": "Haircut"}]) == []

    def test_prefers_the_option_the_shop_ordered_first_on_a_tie(self):
        candidates = [{"id": 1, "name": "Fade"}, {"id": 2, "name": "Skin fade"}]

        # Both match on "fade"; the shop's own ordering breaks the tie.
        assert keyword_fallback("fade please", candidates) == [1, 2]


class TestCandidates:
    def test_only_suggests_services_that_can_be_booked(self):
        profile = make_profile()
        make_service(profile, name="Bookable", is_active=True)
        make_service(profile, name="Retired", is_active=False)

        names = [c["name"] for c in service_candidates(profile.services.all())]

        assert names == ["Bookable"]

    def test_never_suggests_a_shop_that_is_not_taking_bookings(self):
        # Sending the model a closed shop and having it rank first is how a
        # customer ends up on a wasted trip.
        open_shop = make_profile(is_accepting_bookings=True, service_type=ServiceType.BARBERSHOP)
        closed_shop = make_profile(is_accepting_bookings=False, service_type=ServiceType.SPA)
        # Both need something to book, or neither is a candidate at all.
        make_service(open_shop)
        make_service(closed_shop)

        candidates = provider_candidates([open_shop, closed_shop])

        assert [c["id"] for c in candidates] == [open_shop.id]

    def test_never_suggests_a_shop_with_nothing_to_book(self):
        empty = make_profile(is_accepting_bookings=True)

        assert provider_candidates([empty]) == []


class TestSuggestEndpoint:
    def test_falls_back_to_keywords_with_nothing_configured(self, client, settings):
        settings.AI_MODEL = ""
        settings.AI_API_KEY = ""
        settings.AI_ENDPOINT = ""

        profile = make_profile()
        make_service(profile, name="Skin fade")
        make_service(profile, name="Beard trim")

        client_, token = logged_in(make_user())
        response = client_.post(
            f"{V1}/providers/suggest/",
            {"q": "I want a skin fade"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 200
        assert response.data["matched_by"] == "keywords"
        assert [s["name"] for s in response.data["suggestions"]] == ["Skin fade"]

    def test_uses_the_model_when_there_is_one(self, client, settings, monkeypatch):
        settings.AI_MODEL = "test"
        settings.AI_API_KEY = "key"
        settings.AI_ENDPOINT = "https://example.test"
        monkeypatch.setattr(suggestions_module.requests, "post", lambda *a, **k: FakeResponse("[]"))

        profile = make_profile()
        make_service(profile, name="Skin fade")

        client_, token = logged_in(make_user())
        response = client_.post(
            f"{V1}/providers/suggest/",
            {"q": "shorter please"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.data["matched_by"] == "model"

    def test_still_answers_when_the_model_is_down(self, client, settings, monkeypatch):
        settings.AI_MODEL = "test"
        settings.AI_API_KEY = "key"
        settings.AI_ENDPOINT = "https://example.test"

        def boom(*args, **kwargs):
            raise ConnectionError("down")

        monkeypatch.setattr(suggestions_module.requests, "post", boom)

        profile = make_profile()
        make_service(profile, name="Skin fade")

        client_, token = logged_in(make_user())
        response = client_.post(
            f"{V1}/providers/suggest/",
            {"q": "skin fade"},
            content_type="application/json",
            **auth_header(token),
        )

        # A suggestion feature must never take the search box down with it.
        assert response.status_code == 200
        assert response.data["matched_by"] == "keywords"

    def test_says_so_when_there_is_nothing_to_suggest(self, client):
        client_, token = logged_in(make_user())
        response = client_.post(
            f"{V1}/providers/suggest/",
            {"q": "anything"},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 404

    def test_needs_something_to_match_against(self, client):
        client_, token = logged_in(make_user())
        response = client_.post(
            f"{V1}/providers/suggest/",
            {"q": "  "},
            content_type="application/json",
            **auth_header(token),
        )

        assert response.status_code == 400

    def test_needs_an_account(self, client):
        make_profile()
        assert (
            client.post(
                f"{V1}/providers/suggest/", {"q": "fade"}, content_type="application/json"
            ).status_code
            == 401
        )


# ---------------------------------------------------------------------------
# Review summaries
# ---------------------------------------------------------------------------


def make_reviews(provider, ratings_and_comments):
    customers = [make_user(f"cust{i}") for i in range(len(ratings_and_comments))]
    return [
        Review.objects.create(
            provider=provider,
            customer=customer,
            rating=rating,
            comment=comment,
        )
        for (rating, comment), customer in zip(ratings_and_comments, customers, strict=True)
    ]


class TestRatingBreakdown:
    def test_counts_the_distribution(self):
        breakdown = rating_breakdown([FakeReview(r) for r in (1, 5, 5, 3, 5)])

        assert breakdown["total"] == 5
        assert breakdown["average"] == 3.8
        assert breakdown["distribution"]["5"] == 3

    def test_a_verage_and_a_distribution_are_different_facts(self):
        # 3.8 from two fives and three ones is not the same shop as a steady 3.8,
        # which is why the distribution is reported alongside it.
        breakdown = rating_breakdown([FakeReview(r) for r in (5, 5, 1, 1, 1)])

        assert breakdown["average"] == 2.6
        assert breakdown["distribution"]["1"] == 3


class TestSummariseProvider:
    def test_says_so_when_there_are_no_reviews(self):
        payload = summarise_provider(make_profile())

        assert payload["summary"] == "No reviews yet."
        assert payload["total_reviews"] == 0

    def test_does_not_turn_two_reviews_into_a_verdict(self):
        provider = make_profile()
        make_reviews(provider, [(5, "Great"), (5, "Lovely")])

        payload = summarise_provider(provider)

        # Two reviews are anecdotes. Compressing them into a sentence that
        # sounds like a conclusion would be dishonest.
        assert payload["summary_source"] == "too-few-reviews"
        assert "2 reviews" in payload["summary"]

    def test_falls_back_to_the_numbers_with_no_model(self, settings):
        settings.AI_MODEL = ""
        provider = make_profile()
        make_reviews(provider, [(5, f"Great {i}") for i in range(8)])

        payload = summarise_provider(provider)

        assert payload["summary_source"] == "rating-only"
        assert payload["total_reviews"] == 8

    def test_uses_the_model_when_there_is_one(self, settings, monkeypatch):
        settings.AI_MODEL = "test"
        settings.AI_API_KEY = "key"
        settings.AI_ENDPOINT = "https://example.test"
        monkeypatch.setattr(
            summaries_module.requests,
            "post",
            lambda *a, **k: FakeResponse(
                json.dumps(
                    {
                        "summary": "Mostly skin fades, some say they run late.",
                        "highlights": ["Good fades"],
                    }
                )
            ),
        )

        provider = make_profile()
        make_reviews(provider, [(5, f"Great {i}") for i in range(8)])

        payload = summarise_provider(provider)

        assert payload["summary_source"] == "model"
        assert "skin fades" in payload["summary"]
        assert payload["highlights"] == ["Good fades"]

    def test_says_which_reviews_it_came_from(self, settings, monkeypatch):
        # A merchant who thinks a summary is unfair has to be able to read the
        # reviews it was drawn from.
        settings.AI_MODEL = "test"
        settings.AI_API_KEY = "key"
        settings.AI_ENDPOINT = "https://example.test"
        monkeypatch.setattr(
            summaries_module.requests,
            "post",
            lambda *a, **k: FakeResponse(json.dumps({"summary": "Fine"})),
        )

        provider = make_profile()
        reviews = make_reviews(provider, [(5, f"Good {i}") for i in range(8)])

        payload = summarise_provider(provider)

        assert set(payload["from"]) <= {review.id for review in reviews}

    def test_a_model_that_fails_does_not_break_the_page(self, settings, monkeypatch):
        settings.AI_MODEL = "test"
        settings.AI_API_KEY = "key"
        settings.AI_ENDPOINT = "https://example.test"

        def boom(*args, **kwargs):
            raise ConnectionError("down")

        monkeypatch.setattr(summaries_module.requests, "post", boom)

        provider = make_profile()
        make_reviews(provider, [(5, f"Good {i}") for i in range(8)])

        payload = summarise_provider(provider)

        assert payload["summary_source"] == "rating-only"


class TestSummaryParsing:
    def test_accepts_a_fenced_reply(self):
        parsed = _parse('```json\n{"summary": "Good shop", "highlights": []}\n```')

        assert parsed["summary"] == "Good shop"

    def test_rejects_a_reply_with_no_summary(self):
        assert _parse('{"highlights": ["fast"]}') is None

    def test_rejects_prose(self):
        assert _parse("I would rather not.") is None

    def test_caps_the_length_of_a_long_summary(self):
        parsed = _parse(json.dumps({"summary": "x" * 1000}))

        assert len(parsed["summary"]) <= 300

    def test_ignores_highlights_that_are_not_a_list(self):
        parsed = _parse(json.dumps({"summary": "Fine", "highlights": "one big thing"}))

        assert parsed["highlights"] == []


class TestSummaryEndpoint:
    def test_is_readable_without_an_account(self, client, settings):
        settings.AI_MODEL = ""
        provider = make_profile()
        make_reviews(provider, [(5, "Great")])

        # Someone deciding between two shops should not need an account to read
        # what customers say about them.
        assert client.get(f"{V1}/reviews/shops/{provider.id}/summary/").status_code == 200

    def test_404s_for_a_shop_that_does_not_exist(self, client):
        assert client.get(f"{V1}/reviews/shops/999999/summary/").status_code == 404
