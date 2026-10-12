/**
 * Money display and the booking's financial summary.
 *
 * The app never computes an amount — it formats numbers the server sent. What
 * it does decide is what to *say*, and the distinction that matters is between
 * "nothing paid" and "deposit paid, balance still owed". Both read as "not
 * paid yet" to a naive check, and showing "Paid" after a deposit is a lie the
 * provider would act on by booking someone into that chair.
 */

import {
  cancellationNote,
  deadlineSummary,
  formatPaise,
  paymentSummary,
 isUnnamed } from '@/lib/money';
import {
  describeLedgerKind,
  describeLedgerStatus,
} from '@/components/balance-card';
import type { StaffMember } from '@/types/api';
import { formatClock, formatWhen } from '../app/(customer)/waitlist';

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
describe('cancellationNote', () => {
  const quote = (overrides = {}) => ({
    deposit: 90900,
    cancellation_window_hours: 24,
    late_cancel_fee: 45450,
    ...overrides,
  });

  it('says nothing when there is no deposit to lose', () => {
    // Telling every customer about a fee on a booking with no deposit is noise,
    // and noise is how people stop reading the things that matter.
    expect(cancellationNote(quote({ deposit: 0 }))).toBeNull();
  });

  it('explains a free window when nothing is kept', () => {
    expect(cancellationNote(quote({ late_cancel_fee: 0 }))).toContain(
      'Free cancellation up to 24 hours before',
    );
  });

  it('names the fee and the window when something is kept', () => {
    const note = cancellationNote(quote());

    expect(note).toContain('24 hours before');
    expect(note).toContain('₹454.50');
  });

  it('reads naturally when there is no free window at all', () => {
    expect(cancellationNote(quote({ cancellation_window_hours: 0 }))).toContain(
      'Cancel more than any time',
    );
  });

  it('counts down the window in words rather than a date', () => {
    // "24 hours before" is readable on a checkout screen. A timestamp is not.
    expect(cancellationNote(quote())).not.toMatch(/\d{4}-\d{2}-\d{2}/);
  });
});

describe('deadlineSummary', () => {
  it('says free while there is still time', () => {
    expect(deadlineSummary({ is_late_cancellation: false, late_cancel_fee: 45450 })).toBe(
      'Free cancellation',
    );
  });

  it('says what cancelling now costs', () => {
    expect(deadlineSummary({ is_late_cancellation: true, late_cancel_fee: 45450 })).toContain(
      '₹454.50',
    );
  });
});

describe('ledger lines', () => {
  it('describe a kind in words rather than echoing the enum', () => {
    // "platform_fee" on a statement the provider reads is a support ticket.
    expect(describeLedgerKind('earning')).toBe('Appointment earned');
    expect(describeLedgerKind('platform_fee')).toBe('BarberShop fee');
    expect(describeLedgerKind('payout')).toBe('Withdrawal');
    expect(describeLedgerKind('something_new')).toBe('Adjustment');
  });

  it('describe a status in words', () => {
    expect(describeLedgerStatus('pending')).toBe('Pending');
    expect(describeLedgerStatus('cleared')).toBe('Available');
    expect(describeLedgerStatus('paid_out')).toBe('Paid out');
    // A failed transfer is shown as failed rather than silently omitted.
    expect(describeLedgerStatus('voided')).toBe('Failed');
  });
});

describe('staff', () => {
  it('flags the rows the headcount migration created', () => {
    // Real capacity, no name yet. The app says so rather than showing
    // "Staff member 3" as though someone had chosen it.
    const placeholder: StaffMember = {
      id: 1,
      name: 'Staff member 3',
      bio: '',
      photo: null,
      is_active: true,
      is_placeholder: true,
      is_open_today: true,
      hours: [],
    };
    expect(placeholder.is_placeholder).toBe(true);
    expect(isUnnamed(placeholder)).toBe(true);
  });

  it('does not flag a named person', () => {
    expect(isUnnamed({ name: 'Ravi', is_placeholder: false })).toBe(false);
  });
});

describe('a held slot', () => {
  it('says when the hold ends, not just that it is held', () => {
    // "Yours" without a deadline is how somebody is woken by another person
    // taking their slot.
    expect(
      formatWhen(new Date('2026-10-14T10:00:00Z').toISOString()),
    ).toMatch(/\d{1,2}:\d{2}(am|pm)/);
  });

  it('writes the clock the way a person says it', () => {
    const clock = formatClock(new Date('2026-10-14T15:30:00Z').toISOString());
    expect(clock).toMatch(/^\d{1,2}:\d{2}(am|pm)$/);
  });
});
