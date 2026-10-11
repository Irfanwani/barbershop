/**
 * Money display and the booking's financial summary.
 *
 * The app never computes an amount — it formats numbers the server sent. What
 * it does decide is what to *say*, and the distinction that matters is between
 * "nothing paid" and "deposit paid, balance still owed". Both read as "not
 * paid yet" to a naive check, and showing "Paid" after a deposit is a lie the
 * provider would act on by booking someone into that chair.
 */

import { formatPaise, paymentSummary } from '@/lib/money';

describe('formatPaise', () => {
  it('converts paise to rupees', () => {
    expect(formatPaise(25000)).toBe('₹250.00');
  });

  it('keeps the paisa', () => {
    expect(formatPaise(25050)).toBe('₹250.50');
  });

  it('renders nothing as an em dash rather than zero', () => {
    // ₹0.00 is a price. Displaying a missing one as zero is a number somebody
    // acts on.
    expect(formatPaise(null)).toBe('—');
    expect(formatPaise(undefined)).toBe('—');
    expect(formatPaise(Number.NaN)).toBe('—');
  });
});

describe('paymentSummary', () => {
  const booking = (overrides = {}) => ({
    deposit: 90900,
    amount_paid: 0,
    amount_due: 303000,
    total: 303000,
    ...overrides,
  });

  it('says so when nothing has been paid', () => {
    expect(paymentSummary(booking())).toBe('Nothing paid yet');
  });

  it('does not say "paid" after a deposit', () => {
    const summary = paymentSummary(booking({ amount_paid: 90900, amount_due: 212100 }));

    // The mistake this whole feature exists to prevent.
    expect(summary).not.toContain('Paid in full');
    expect(summary).toContain('₹2121.00 due at the shop');
  });

  it('says paid in full only when nothing is due', () => {
    expect(paymentSummary(booking({ amount_paid: 303000, amount_due: 0 }))).toBe(
      'Paid in full',
    );
  });

  it('distinguishes a part payment from a deposit', () => {
    const summary = paymentSummary(booking({ amount_paid: 40000, amount_due: 263000 }));

    expect(summary).toContain('Part-paid');
    expect(summary).toContain('₹2630.00 outstanding');
  });

  it('handles a booking with no deposit policy', () => {
    const summary = paymentSummary(
      booking({ deposit: 0, amount_paid: 25250, amount_due: 0, total: 25250 }),
    );

    expect(summary).toBe('Paid in full');
  });
});