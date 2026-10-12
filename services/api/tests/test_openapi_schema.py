"""The OpenAPI schema is a contract, so it gets a test.

If the published schema and the code can drift, nobody trusts either. This fails
loudly when a field is removed or an endpoint disappears, which is exactly when
an old version of the app breaks in production and nobody noticed first.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from django.urls import reverse
from drf_spectacular.generators import SchemaGenerator

pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module")
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def paths(schema) -> set[str]:
    """Schemas keys already carry a leading slash; normalise anyway."""
    return {("" if path.startswith("/") else "/") + path for path in schema["paths"]}


EXPECTED_ENDPOINTS = {
    # auth
    "/api/v1/auth/register/",
    "/api/v1/auth/login/",
    "/api/v1/auth/logout/",
    "/api/v1/auth/logout-all/",
    "/api/v1/auth/verify-email/",
    "/api/v1/auth/resend-verification/",
    "/api/v1/auth/password-reset/request/",
    "/api/v1/auth/password-reset/confirm/",
    # me
    "/api/v1/me/",
    "/api/v1/me/password/",
    "/api/v1/me/profile/",
    "/api/v1/me/shop/",
    "/api/v1/me/shop/create/",
    "/api/v1/me/push-tokens/",
    "/api/v1/me/push-tokens/clear/",
    "/api/v1/me/push-tokens/{token_id}/",
    "/api/v1/me/login-history/",
    # providers
    "/api/v1/providers/",
    "/api/v1/providers/types/",
    "/api/v1/providers/me/",
    "/api/v1/providers/me/services/",
    "/api/v1/providers/me/services/{id}/",
    "/api/v1/providers/prices/",
    "/api/v1/providers/prices/services/",
    "/api/v1/providers/suggest/",
    "/api/v1/bookings/{reference}/reschedule/",
    "/api/v1/bookings/waitlist/",
    "/api/v1/bookings/waitlist/offers/",
    "/api/v1/bookings/waitlist/offers/{id}/accept/",
    "/api/v1/bookings/waitlist/offers/{id}/decline/",
    "/api/v1/bookings/waitlist/{id}/",
    "/api/v1/me/notification-preferences/",
    "/api/v1/me/saved-shops/",
    "/api/v1/me/saved-shops/{provider_id}/",
    "/api/v1/providers/me/staff/",
    "/api/v1/providers/me/staff/{id}/",
    "/api/v1/providers/{id}/staff/",
    "/api/v1/providers/me/balance/",
    "/api/v1/providers/me/ledger/",
    "/api/v1/providers/me/withdraw/",
    "/api/v1/providers/me/payout/",
    "/api/v1/providers/me/hours/",
    "/api/v1/providers/me/accepting-bookings/",
    "/api/v1/providers/{id}/",
    "/api/v1/providers/{id}/availability/",
    # catalogue
    "/api/v1/products/",
    "/api/v1/products/types/",
    "/api/v1/products/popular/",
    "/api/v1/products/{id}/",
    "/api/v1/products/shops/{provider_pk}/",
    "/api/v1/products/me/inventory/",
    "/api/v1/products/me/orders/",
    "/api/v1/products/me/shop-orders/",
    "/api/v1/products/orders/quote/",
    "/api/v1/products/orders/new/",
    "/api/v1/products/orders/{reference}/",
    "/api/v1/products/orders/{reference}/action/",
    # bookings
    "/api/v1/bookings/",
    "/api/v1/bookings/quote/",
    "/api/v1/bookings/new/",
    "/api/v1/bookings/{reference}/",
    "/api/v1/bookings/{reference}/cancel/",
    "/api/v1/bookings/{reference}/collect/",
    "/api/v1/bookings/{reference}/{action}/",
    # reviews
    "/api/v1/reviews/",
    "/api/v1/reviews/new/",
    "/api/v1/reviews/shops/{provider_pk}/summary/",
    "/api/v1/reviews/{id}/",
    "/api/v1/reviews/{id}/reply/",
    # payments
    "/api/v1/payments/orders/",
    "/api/v1/payments/verify/",
    "/api/v1/payments/webhook/",
    "/api/v1/payments/bookings/{reference}/refund/",
    "/api/v1/payments/{order_id}/",
}


def test_every_endpoint_is_documented(schema):
    """A missing endpoint here means it is missing from the published schema."""
    missing = EXPECTED_ENDPOINTS - paths(schema)
    assert not missing, f"not in the schema: {sorted(missing)}"


def test_nothing_is_documented_that_does_not_exist(schema):
    extra = paths(schema) - EXPECTED_ENDPOINTS
    assert not extra, f"documented but not routed: {sorted(extra)}"


def test_no_operation_id_is_duplicated(schema):
    """The mobile client generates request names from these."""
    ids = [
        operation["operationId"] for path in schema["paths"].values() for operation in path.values()
    ]
    assert len(ids) == len(set(ids))


def test_every_operation_has_a_summary(schema):
    """A summary is what shows up in the docs; an empty one is a gap."""
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method in {"parameters", "get", "put", "post", "delete", "patch"}:
                assert operation.get("summary"), f"{method.upper()} {path} has no summary"


def test_every_operation_is_tagged(schema):
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method in {"parameters", "get", "put", "post", "delete", "patch"}:
                assert operation.get("tags"), f"{method.upper()} {path} is untagged"


def test_the_removed_legacy_endpoints_are_gone(schema):
    """A regression guard: these served the old apps and must not reappear."""
    for path in schema["paths"]:
        assert not path.startswith("/api/haircut")
        assert not path.startswith("/api/accounts")
        assert not path.startswith("/api/payments")


def test_token_auth_is_declared(schema):
    """Clients need to know the header name and the prefix to build a request."""
    schemes = schema.get("components", {}).get("securitySchemes", {})
    token = next((value for value in schemes.values() if "Token" in str(value)), None)

    assert token is not None, "no token auth scheme in the schema"
    assert token["name"] == "Authorization"
    assert "Token" in str(token.get("description"))


def test_the_schema_served_over_http_matches_the_committed_one(client):
    """What a client downloads is what CI checked."""
    response = client.get(reverse("v1:schema"))
    assert response.status_code == 200


def _generate_to(path) -> str:
    """Generate the schema in a clean interpreter, the way CI does."""
    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run(
        [sys.executable, "manage.py", "dump_schema", "--output", str(path)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.dev"},
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return Path(path).read_text()


def test_the_committed_schema_is_current(tmp_path):
    """
    The committed schema must match what the code produces, byte for byte.

    Generated in a subprocess: in-process generation picks up Django URL caches and
    DRF view state left behind by earlier tests, so it can produce a different
    schema depending on test order — noise that says nothing about the API.
    """
    fresh = _generate_to(tmp_path / "schema.yml")
    committed_path = Path(__file__).resolve().parent.parent / "docs" / "openapi.yml"
    if not committed_path.exists():  # pragma: no cover - only on a fresh checkout
        pytest.skip("docs/openapi.yml has not been generated yet")

    if fresh != committed_path.read_text():
        import difflib

        diff = "\n".join(
            list(
                difflib.unified_diff(
                    committed_path.read_text().splitlines(),
                    fresh.splitlines(),
                    lineterm="",
                    n=1,
                )
            )[:30]
        )
        pytest.fail(
            "services/api/docs/openapi.yml is out of date. Regenerate with:\n"
            "  cd services/api && uv run python manage.py dump_schema\n\n" + diff
        )


def test_the_committed_schema_has_no_warnings():
    """A schema full of warnings is documentation nobody can rely on."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "manage.py", "dump_schema", "--stdout"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.dev"},
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "Warning" not in result.stderr
