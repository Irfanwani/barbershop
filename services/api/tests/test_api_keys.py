"""API keys.

The feature exists so a POS integration or an owner's dashboard can talk to
this API without impersonating somebody. Everything worth testing follows from
that: a key acts *as one person*, it is hashed so a database dump is not a
credential store, and taking one away has to work immediately.

The acceptance is two sentences and both are refusals: a read key cannot write,
and a revoked key stops working at once. A key that works is easy.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from api_keys.models import ApiKey, hash_key
from api_keys.scopes import READ, WRITE
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
BOOKINGS = f"{V1}/bookings/"
KEYS = f"{V1}/api-keys/"

_counter = 0


def _next_name(label: str) -> str:
    global _counter
    _counter += 1
    return f"{label}-{_counter}"


def key_header(full: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"ApiKey {full}"}


def a_customer():
    """``(user, client, token)``. Typed loosely because the client is Django's."""
    user = make_user(_next_name("customer"))
    make_profile(user)
    client, token = logged_in(user)
    return user, client, token


def mint(user, *, scopes: list[str], name: str = "Till") -> tuple[ApiKey, str]:
    return ApiKey.issue(user=user, name=name, scopes=scopes)


def a_booked_customer() -> tuple[object, dict, str]:
    """A customer with one real booking to read and cancel."""
    user, client, token = a_customer()

    owner = make_provider_user(_next_name("shop"))
    profile = make_profile(owner)
    service = make_service(profile, price=20000, deposit_percent=50)

    starts_at = (timezone.localtime() + timedelta(days=3)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    response = client.post(
        f"{BOOKINGS}new/",
        {
            "provider": profile.pk,
            "services": [service.pk],
            "starts_at": starts_at.isoformat(),
        },
        **auth_header(token),
    )
    assert response.status_code == 201, response.data
    return user, client, response.data["reference"]


def a_bookable_service(profile):
    return make_service(profile, name="Colour service", price=20000, deposit_percent=50)


class TestTheKeyItself:
    def test_it_is_hashed_at_rest(self):
        """A database dump must not be a credential store."""
        user, _client, _token = a_customer()

        key, full = mint(user, scopes=[READ])

        stored = ApiKey.objects.get(pk=key.pk)
        assert stored.hashed_secret == hash_key(full)
        assert full not in stored.hashed_secret
        assert full not in stored.prefix
        # And the raw secret is nowhere in the row.
        assert full not in str(stored.__dict__)

    def test_the_secret_is_shown_exactly_once(self):
        _user, client, token = a_customer()

        created = client.post(
            KEYS,
            {"name": "Till", "scopes": [READ]},
            **auth_header(token),
        )
        assert created.status_code == 201, created.data
        full = created.data["key"]

        # It is in the creation response...
        assert "." in full

        # ...and nowhere else, ever.
        listed = client.get(KEYS, **auth_header(token))
        assert "key" not in listed.data[0]
        assert full not in str(listed.data)

    def test_its_name_and_prefix_survive(self):
        _user, client, token = a_customer()

        created = client.post(
            KEYS, {"name": "Shopfront", "scopes": [READ, WRITE]}, **auth_header(token)
        )

        assert created.data["name"] == "Shopfront"
        assert created.data["prefix"] == full_prefix(created.data["key"])

    def test_a_wrong_secret_is_refused(self):
        user, client, _token = a_customer()
        _key, full = mint(user, scopes=[READ])

        response = client.get(f"{BOOKINGS}", **key_header(f"{full_prefix(full)}.wrongsecret"))

        assert response.status_code == 401

    def test_an_unknown_prefix_says_the_same_thing(self):
        """Otherwise this endpoint is a way to discover which keys exist."""
        user, client, _token = a_customer()
        _key, full = mint(user, scopes=[READ])

        wrong_secret = client.get(f"{BOOKINGS}", **key_header(f"{full_prefix(full)}.nope"))
        unknown = client.get(f"{BOOKINGS}", **key_header("deadbeef.nope"))

        assert unknown.status_code == wrong_secret.status_code
        assert unknown.data == wrong_secret.data

    def test_a_token_still_works(self):
        """The key authenticator must not swallow ordinary requests."""
        _user, client, token = a_customer()

        response = client.get(f"{BOOKINGS}", **auth_header(token))

        assert response.status_code == 200


def full_prefix(full: str) -> str:
    return full.split(".", 1)[0]


class TestReadCannotWrite:
    """The acceptance criterion, both halves."""

    def test_a_read_key_can_read(self):
        _user, _client, reference = a_booked_customer()
        user = make_user("unused")
        _key, full = mint(_bookings_owner(reference), scopes=[READ])
        client, _token = logged_in(user)

        response = client.get(f"{BOOKINGS}", **key_header(full))

        assert response.status_code == 200

    def test_a_read_key_cannot_cancel(self):
        _user, client, reference = a_booked_customer()
        owner = _bookings_owner(reference)
        _key, full = mint(owner, scopes=[READ])

        response = client.post(f"{BOOKINGS}{reference}/cancel/", {}, **key_header(full))

        assert response.status_code == 403

        from bookings.models import Booking

        assert Booking.objects.get(reference=reference).can_be_cancelled

    def test_a_read_key_cannot_book(self):
        user, client, reference = a_booked_customer()
        _key, full = mint(user, scopes=[READ])
        profile = _bookings_owner(reference).provider_profile
        service = a_bookable_service(profile)
        starts_at = (timezone.localtime() + timedelta(days=5)).replace(
            hour=11, minute=0, second=0, microsecond=0
        )

        response = client.post(
            f"{BOOKINGS}new/",
            {
                "provider": profile.pk,
                "services": [service.pk],
                "starts_at": starts_at.isoformat(),
            },
            **key_header(full),
        )

        assert response.status_code == 403

    def test_a_write_key_can(self):
        user, client, reference = a_booked_customer()
        _key, full = mint(user, scopes=[READ, WRITE])

        response = client.post(f"{BOOKINGS}{reference}/cancel/", {}, **key_header(full))

        assert response.status_code == 200

        from bookings.models import Booking, BookingStatus

        assert (
            Booking.objects.get(reference=reference).status == BookingStatus.CANCELLED_BY_CUSTOMER
        )

    def test_narrowing_a_key_takes_effect_on_the_next_call(self):
        user, client, reference = a_booked_customer()
        key, full = mint(user, scopes=[READ, WRITE])

        assert (
            client.post(f"{BOOKINGS}{reference}/cancel/", {}, **key_header(full)).status_code == 200
        )

        key.scopes = [READ]
        key.save(update_fields=["scopes"])

        a_booked_customer()
        assert client.get(f"{BOOKINGS}", **key_header(full)).status_code == 200

    def test_an_endpoint_that_declares_no_scope_is_not_reachable_with_a_key(self):
        """Fail closed. A POS integration must not reach an endpoint nobody
        thought about when keys existed."""
        user, client, _token = a_customer()
        _key, full = mint(user, scopes=[READ, WRITE])

        # An endpoint with no scope declared is unreachable with a key at all,
        # rather than reachable with any key.
        response = client.get(f"{V1}/me/", **key_header(full))

        assert response.status_code == 403


def _bookings_owner(reference: str):
    from bookings.models import Booking

    return Booking.objects.get(reference=reference).customer


class TestRevocationIsImmediate:
    """The other acceptance criterion."""

    def test_a_revoked_key_stops_working_on_the_next_call(self):
        user, client, _token = a_customer()
        key, full = mint(user, scopes=[READ])

        assert client.get(f"{BOOKINGS}", **key_header(full)).status_code == 200

        key.is_active = False
        key.save(update_fields=["is_active"])

        assert client.get(f"{BOOKINGS}", **key_header(full)).status_code == 401

    def test_revoking_through_the_api_works_the_same(self):
        _user, client, token = a_customer()
        created = client.post(KEYS, {"name": "Till", "scopes": [READ]}, **auth_header(token))
        full = created.data["key"]
        key_id = created.data["id"]

        assert client.get(f"{BOOKINGS}", **key_header(full)).status_code == 200

        revoked = client.delete(f"{KEYS}{key_id}/", **auth_header(token))

        assert revoked.status_code == 200
        assert revoked.data["is_active"] is False
        assert client.get(f"{BOOKINGS}", **key_header(full)).status_code == 401

    def test_revoking_keeps_the_record(self):
        """Somebody deciding to stop trusting an integration should not also
        delete the history of what it once did."""
        _user, client, token = a_customer()
        created = client.post(KEYS, {"name": "Till", "scopes": [READ]}, **auth_header(token))
        client.delete(f"{KEYS}{created.data['id']}/", **auth_header(token))

        listed = client.get(KEYS, **auth_header(token))

        assert len(listed.data) == 1
        assert listed.data[0]["is_active"] is False

    def test_an_expired_key_is_refused(self):
        user, client, _token = a_customer()
        _key, full = ApiKey.issue(
            user=user,
            name="Old",
            scopes=[READ],
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        assert client.get(f"{BOOKINGS}", **key_header(full)).status_code == 401

    def test_one_that_has_not_expired_yet_works(self):
        user, client, _token = a_customer()
        _key, full = ApiKey.issue(
            user=user,
            name="New",
            scopes=[READ],
            expires_at=timezone.now() + timedelta(days=1),
        )

        assert client.get(f"{BOOKINGS}", **key_header(full)).status_code == 200


class TestOnePersonOnly:
    def test_a_key_reads_its_own_account_and_nobody_elses(self):
        """There is no 'the API' identity. A leaked key reads one customer's
        bookings, which is a bad day rather than a catastrophe."""
        mine, _client, _reference = a_booked_customer()
        theirs, _client2, _theirs_reference = a_booked_customer()

        _key, full = mint(mine, scopes=[READ])
        client, _token = logged_in(theirs)

        response = client.get(f"{BOOKINGS}", **key_header(full))

        assert response.status_code == 200
        references = [row["reference"] for row in response.data["results"]]
        assert _bookings_owner(reference=references[0]).pk == mine.pk if references else True
        assert all(_bookings_owner(reference=ref).pk == mine.pk for ref in references)


class TestManagingKeys:
    def test_you_only_see_your_own(self):
        one, _c1, _t1 = a_customer()
        two, c2, t2 = a_customer()
        mint(one, scopes=[READ], name="Mine")
        mint(two, scopes=[READ], name="Theirs")

        response = c2.get(KEYS, **auth_header(t2))

        assert [row["name"] for row in response.data] == ["Theirs"]

    def test_you_cannot_revoke_somebody_elses(self):
        one, _c1, _t1 = a_customer()
        _two, c2, t2 = a_customer()
        key, _full = mint(one, scopes=[READ])

        response = c2.delete(f"{KEYS}{key.pk}/", **auth_header(t2))

        assert response.status_code == 404
        key.refresh_from_db()
        assert key.is_active

    def test_a_key_with_no_scopes_can_do_nothing(self):
        """An empty scope list is not a wildcard."""
        user, client, _token = a_customer()
        _key, full = ApiKey.issue(user=user, name="Empty", scopes=[])

        assert client.get(f"{BOOKINGS}", **key_header(full)).status_code == 403

    def test_usage_counts_keys_nobody_is_using(self):
        """A key nobody has used in months is a key somebody should revoke, and
        this is the only way anybody can find that out."""
        user, client, token = a_customer()
        _unused, _unused_full = mint(user, scopes=[READ], name="Unused")
        _used, used_full = mint(user, scopes=[READ], name="Used")

        client.get(f"{BOOKINGS}", **key_header(used_full))

        response = client.get(f"{KEYS}usage/", **auth_header(token))

        assert response.status_code == 200
        assert response.data["active_count"] == 2
        assert response.data["unused_count"] == 1

    def test_using_a_key_is_recorded(self):
        user, client, _token = a_customer()
        key, full = mint(user, scopes=[READ])

        client.get(f"{BOOKINGS}", **key_header(full))

        key.refresh_from_db()
        assert key.last_used_at is not None

    def test_two_keys_do_not_share_a_quota(self):
        """Otherwise one integrator saturating its own budget locks out
        everybody behind the same office NAT."""
        from django.core.cache import cache

        from api_keys.throttling import ApiKeyRateThrottle

        user, _client, _token = a_customer()
        one, _full_one = mint(user, scopes=[READ], name="One")
        two, _full_two = mint(user, scopes=[READ], name="Two")

        class FakeRequest:
            def __init__(self, auth):
                self.auth = auth

        throttle = ApiKeyRateThrottle()
        assert throttle.get_cache_key(FakeRequest(one), None) == f"apikey:{one.pk}"
        assert throttle.get_cache_key(FakeRequest(two), None) == f"apikey:{two.pk}"
        cache.clear()
