/**
 * Display money.
 *
 * The app never computes an amount — every figure here is formatted from a
 * number the server sent. This exists so "₹2,500.00" is rendered the same way
 * in twelve screens instead of eleven and a typo.
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
 * balance owed". Both read as "not paid yet" to a naive check, and showing
 * "Paid" after a deposit would be a lie.
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
