"""Razorpay integration.

Payment state moves only from a verified webhook. The old ``PUT
/api/payments/createorder`` set ``paid=True`` on any appointment id in the
request body after checking only that someone was authenticated — so any user
could mark any booking paid.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

import requests
from django.conf import settings

from payments.models import Payment, PaymentStatus

logger = logging.getLogger(__name__)

RAZORPAY_API = "https://api.razorpay.com/v1"
TIMEOUT = 10


def credentials_configured() -> bool:
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def _auth() -> tuple[str, str]:
    return settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """Check Razorpay's HMAC signature over the raw request body.

    Compares with ``compare_digest`` so a caller cannot learn the signature one
    byte at a time.
    """
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def sign_webhook_payload(body: bytes) -> str:
    """Sign a body the way Razorpay would.

    Only used by tests, so it is the one place the signing side of the HMAC
    lives. If this and :func:`verify_webhook_signature` ever disagreed, every
    webhook test would pass and no webhook would work — which is the sort of
    thing a test suite is supposed to make impossible rather than merely
    unlikely.
    """
    import hashlib
    import hmac

    secret = settings.RAZORPAY_WEBHOOK_SECRET
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def create_order(amount: int, currency: str, receipt: str, notes: dict | None = None) -> dict:
    """Create a Razorpay order for ``amount`` in the smallest currency unit."""
    if not credentials_configured():
        raise RuntimeError("Razorpay credentials are not configured.")

    response = requests.post(
        f"{RAZORPAY_API}/orders",
        json={
            "amount": amount,
            "currency": currency,
            "receipt": receipt,
            "notes": notes or {},
        },
        auth=_auth(),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Check the signature the app returns after a successful checkout."""
    if not credentials_configured() or not signature:
        return False
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def create_refund(*, payment_id: str, amount: int, notes: dict | None = None) -> dict:
    """Ask Razorpay for money back.

    Returns whatever the gateway accepted. A refund is asynchronous, so this
    being successful means "asked", not "done" — the final state arrives by
    webhook.
    """
    response = requests.post(
        f"{RAZORPAY_API}/payments/{payment_id}/refund",
        auth=_auth(),
        json={"amount": amount, "notes": notes or {}},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def fetch_refund(refund_id: str) -> dict:
    response = requests.get(f"{RAZORPAY_API}/refunds/{refund_id}", auth=_auth(), timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_payment(payment_id: str) -> dict:
    response = requests.get(f"{RAZORPAY_API}/payments/{payment_id}", auth=_auth(), timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def register_fund_account(payout) -> bool:
    """Ask Razorpay to verify a provider's payout account.

    Failure is logged and swallowed: the provider can retry, and losing the
    connection should not lose the details they just typed in.
    """
    from providers.models import ProviderPayout

    if not credentials_configured():
        payout.verification_status = ProviderPayout.VerificationStatus.SUBMITTED
        payout.save(update_fields=["verification_status", "updated_at"])
        return False

    try:
        response = requests.post(
            f"{RAZORPAY_API}/fund_accounts",
            json={
                "account_type": payout.account_type,
                "business_type": payout.business_type,
                "business_name": payout.business_name,
                "beneficiary_name": payout.beneficiary_name,
                "account_number": payout.account_number,
                "ifsc_code": payout.ifsc_code,
            },
            auth=_auth(),
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
    except Exception:
        logger.exception("Could not register a fund account for payout %s", payout.pk)
        payout.verification_status = ProviderPayout.VerificationStatus.SUBMITTED
        payout.save(update_fields=["verification_status", "updated_at"])
        return False

    payout.razorpay_account_id = body.get("id", "")
    payout.razorpay_destination = (body.get("fund_transfer") or {}).get("destination", "")
    payout.verification_status = ProviderPayout.VerificationStatus.SUBMITTED
    payout.save(
        update_fields=[
            "razorpay_account_id",
            "razorpay_destination",
            "verification_status",
            "updated_at",
        ]
    )
    return True


def mark_captured(payment: Payment, payment_id: str, signature: str) -> Payment:
    """Advance a payment to captured. Only ever called from the webhook."""
    payment.status = PaymentStatus.CAPTURED
    payment.razorpay_payment_id = payment_id
    payment.razorpay_signature = signature or ""
    payment.captured_at = timezone_now()
    payment.save(
        update_fields=[
            "status",
            "razorpay_payment_id",
            "razorpay_signature",
            "captured_at",
            "updated_at",
        ]
    )
    return payment


def timezone_now():
    from django.utils import timezone

    return timezone.now()


def now_timestamp() -> int:
    return int(time.time())


def create_payout(
    *, account_id: str, amount: int, reference: str, notes: dict | None = None
) -> dict:
    """Send money to a provider's bank account.

    A Razorpay transfer needs an absolute amount in paise, so a provider cannot
    be paid out in anything else.
    """
    response = requests.post(
        f"{RAZORPAY_API}/payouts",
        auth=_auth(),
        json={
            "account_number": account_id,
            "amount": amount,
            "currency": "INR",
            "mode": "IMPS",
            "purpose": "settlement",
            "reference_id": reference,
            "notes": notes or {},
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def fetch_payout(payout_id: str) -> dict:
    response = requests.get(f"{RAZORPAY_API}/payouts/{payout_id}", auth=_auth(), timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()
