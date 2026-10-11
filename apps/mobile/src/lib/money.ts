/**
 * Display money, and say what a cancellation costs.
 *
 * The app never computes an amount — every figure here is formatted from a
 * number the server sent. What it does decide is what to *say*, and the
 * distinction that matters is between "nothing paid" and "deposit paid, balance
 * still owed". Both read as "not paid yet" to a naive check, and showing "Paid"
 * after a deposit is a lie the provider would act on by booking someone into
 * that chair.
 */

/** Paise to a rupee string. Non-numbers render as an em dash, never ₹0.00. */
export function formatPaise(minor: number | null | undefined): string {
  if (typeof minor !== 'number' || !Number.isFinite(minor)) return '\u2014';
  return `\u20b9${(minor / 100).toFixed(2)}`;
}

/**
 * One line describing where a booking stands financially.
 *
 * The distinction that matters is between "nothing paid" and "deposit paid,
 * balance owed". Showing "Paid" after a deposit is the single easiest mistake
 * this feature invites.
 */
export function paymentSummary(booking: {
  deposit: number;
  amount_paid: number;
  amount_due: number;
  total: number;
}): string {
  if (booking.amount_due === 0) return 'Paid in full';
  if (booking.amount_paid === 0) return 'Nothing paid yet';
  if (booking.amount_paid >= booking.deposit && booking.deposit > 0) {
    return `Deposit paid \u00b7 ${formatPaise(booking.amount_due)} due at the shop`;
  }
  return `Part-paid \u00b7 ${formatPaise(booking.amount_due)} outstanding`;
}

/**
 * A sentence about cancelling, for the checkout sheet.
 *
 * Only shown when cancelling actually costs something. Telling every customer
 * about a fee on a booking with no deposit would be noise, and noise is how
 * people stop reading the things that matter.
 */
export function cancellationNote(quote: {
  deposit: number;
  cancellation_window_hours: number;
  late_cancel_fee: number;
}): string | null {
  if (quote.deposit === 0) return null;
  if (quote.late_cancel_fee === 0) {
    return `Free cancellation up to ${quote.cancellation_window_hours} hours before.`;
  }

  const window =
    quote.cancellation_window_hours === 0
      ? 'any time'
      : `${quote.cancellation_window_hours} hours before`;

  return `Cancel more than ${window} and you get all of it back. Inside that, ` +
    `${formatPaise(quote.late_cancel_fee)} is kept.`;
}

/** How long until the free-cancellation deadline, in words. */
export function deadlineSummary(booking: {
  is_late_cancellation: boolean;
  late_cancel_fee: number;
}): string {
  if (booking.is_late_cancellation) {
    return `Late to cancel \u00b7 ${formatPaise(booking.late_cancel_fee)} of the deposit is kept`;
  }
  return 'Free cancellation';
}
