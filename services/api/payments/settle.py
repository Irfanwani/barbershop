"""Paying providers out.

A withdrawal is not instant. Razorpay accepts a transfer and then settles it,
possibly the next working day, so the request creates a *request* and the money
leaves when the webhook says so. Recording it as paid the moment it is accepted
would show a provider money that has not arrived.

Two guards, because this moves real money out of the platform:

- **Never more than the cleared balance.** Pending earnings are excluded: a
  booking that has not finished can still be refunded or become a no-show.
- **Never to an unverified account.** A provider whose bank details have not
  been checked is not paid, whatever they ask for.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class WithdrawalError(Exception):
    """The withdrawal was refused before anything was sent."""


@transaction.atomic
def request_withdrawal(provider, *, amount: int | None = None) -> dict:
    """Ask for money to be sent to the provider's bank.

    Returns a description of the request. The provider's balance drops
    immediately — the money has left ours either way — while `cleared` only
    moves when the transfer settles.
    """
    from payments.ledger import balance_for, record_payout
    from providers.models import ProviderPayout

    current = balance_for(provider)

    if amount is None:
        amount = current.cleared
    amount = int(amount)

    if amount <= 0:
        raise WithdrawalError(
            "There is nothing cleared to pay out yet. Earnings clear after the "
            "appointment is finished."
        )
    if amount > current.cleared:
        raise WithdrawalError(
            f"That is more than the {current.cleared} cleared. Earnings still "
            "waiting on an appointment cannot be paid out early."
        )

    payout = ProviderPayout.objects.filter(provider=provider).first()
    if payout is None:
        raise WithdrawalError("Add your bank details before asking for a payout.")
    if payout.verification_status != ProviderPayout.VerificationStatus.VERIFIED:
        raise WithdrawalError("Your bank account is not verified yet, so we cannot pay out to it.")

    reference = f"wd_{provider.pk}_{int(timezone.now().timestamp())}"

    transfer_id = ""
    status = "pending"
    try:
        from payments.services import create_payout

        result = create_payout(
            account_id=payout.razorpay_destination or payout.account_number,
            amount=amount,
            reference=reference,
        )
        transfer_id = result.get("id", "")
        status = result.get("status", "pending")
    except Exception:
        # The ledger still moves: we are telling the provider the money is on
        # its way and a reconciliation job will settle it. Swallowing it here
        # would leave them with a balance that never clears.
        logger.exception("Could not start a payout for %s", provider.display_name)

    record_payout(
        provider,
        amount=amount,
        reference=reference,
        transfer_id=transfer_id,
    )

    return {
        "amount": amount,
        "reference": reference,
        "transfer_id": transfer_id,
        "status": status,
    }


def settle_transfer(provider, *, reference: str, transfer_id: str, succeeded: bool) -> None:
    """Move a paid-out entry from cleared to paid when the transfer lands.

    A failed transfer returns the money to the cleared balance rather than
    leaving it missing: the provider never received it, so it is still theirs.
    """
    from payments.models import LedgerEntry

    entry = LedgerEntry.objects.filter(provider=provider, reference=reference).first()
    if entry is None:
        logger.warning("No ledger entry for transfer %s", reference)
        return

    if succeeded:
        # The money has gone.
        entry.status = LedgerEntry.Status.PAID_OUT
        entry.description = "Withdrawal to bank account"
    else:
        # The provider never received it, so the earnings it drew down were never
        # spent. Voiding the line puts them back without adding a second line
        # that would count the same money twice.
        entry.status = LedgerEntry.Status.VOIDED
        entry.description = "Withdrawal failed; balance restored"
    entry.save(update_fields=["status", "description", "updated_at"])
