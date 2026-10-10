/**
 * The two pieces of app-wide state that have real rules: where the app sends
 * you after sign-in, and which notifications you have agreed to receive.
 */

import {
  BOOKING_STATUS_LABELS,
  destinationFor,
  type Destination,
} from '@/api/endpoints';
import { cn } from '@/lib/cn';
import { formatRelative, formatWhen } from '@/components/booking-row';
import {
  NOTIFICATION_CATALOGUE,
  useNotificationPreferencesStore,
  notificationEnabled,
} from '@/store/notification-preferences';
import type { BookingStatus, User } from '@/types/api';

// ---------------------------------------------------------------------------

function user(overrides: Partial<User> = {}): User {
  return {
    id: 1,
    username: 'jane',
    email: 'jane@example.com',
    first_name: 'Jane',
    last_name: 'Doe',
    display_name: 'Jane Doe',
    role: 'customer',
    is_verified: true,
    verified_at: null,
    avatar: null,
    phone: '',
    timezone_name: '',
    has_customer_profile: true,
    has_provider_profile: false,
    has_payout: false,
    service_count: 0,
    onboarding_complete: true,
    ...overrides,
  };
}

describe('destinationFor', () => {
  const cases: [string, ReturnType<typeof user> | null, boolean, Destination][] = [
    ['a new visitor sees the welcome screen', null, false, 'welcome'],
    ['a returning visitor goes straight to sign in', null, true, 'login'],
    ['an unverified account goes to verification', user({ is_verified: false }), true, 'verify-email'],
    ['a customer who has not onboarded is asked to', user({ onboarding_complete: false }), true, 'onboarding'],
    ['a finished customer lands on browse', user(), true, 'customer'],
    [
      'a finished provider lands on their dashboard',
      user({ role: 'provider', onboarding_complete: true }),
      true,
      'provider',
    ],
  ];

  it.each(cases)('%s', (_label, account, seenWelcome, expected) => {
    expect(destinationFor(account, seenWelcome)).toBe(expected);
  });

  it('never sends an unverified account past verification, whatever its role', () => {
    for (const role of ['customer', 'provider'] as const) {
      const account = user({ role, is_verified: false });
      expect(destinationFor(account, true)).toBe('verify-email');
    }
  });
});

describe('BOOKING_STATUS_LABELS', () => {
  it('labels every status the API can return', () => {
    const every: BookingStatus[] = [
      'pending_payment',
      'awaiting_confirmation',
      'confirmed',
      'completed',
      'cancelled_by_customer',
      'cancelled_by_provider',
      'no_show',
      'refunded',
    ];

    for (const status of every) {
      expect(BOOKING_STATUS_LABELS[status]).toBeTruthy();
    }
  });
});

// ---------------------------------------------------------------------------

describe('cn', () => {
  it('joins and drops falsy values', () => {
    expect(cn('a', false, null, undefined, 'b')).toBe('a b');
  });

  it('flattens nested arrays', () => {
    expect(cn(['a', ['b', null, 'c']])).toBe('a b c');
  });

  it('returns an empty string when given nothing usable', () => {
    expect(cn(null, undefined, false)).toBe('');
  });
});

// ---------------------------------------------------------------------------

describe('formatRelative', () => {
  const inMinutes = (minutes: number) => new Date(Date.now() + minutes * 60_000).toISOString();

  it('reads in minutes below an hour', () => {
    expect(formatRelative(inMinutes(30))).toBe('in 30 min');
  });

  it('reads in hours below a day', () => {
    expect(formatRelative(inMinutes(180))).toBe('in 3 h');
  });

  it('reads in days beyond that', () => {
    expect(formatRelative(inMinutes(60 * 48))).toBe('in 2 d');
  });

  it('reads the past in the past tense', () => {
    expect(formatRelative(inMinutes(-100))).toBe('2 h ago');
    expect(formatRelative(inMinutes(-5))).toBe('5 min ago');
  });
});

describe('formatWhen', () => {
  it('renders a date a person can read', () => {
    const iso = new Date(2026, 0, 14, 15, 30).toISOString();
    const rendered = formatWhen(iso);

    expect(rendered).toContain('Jan');
    expect(rendered).toContain('14');
  });
});

// ---------------------------------------------------------------------------

describe('notification preferences', () => {
  beforeEach(() => {
    useNotificationPreferencesStore.setState({
      preferences: Object.fromEntries(
        NOTIFICATION_CATALOGUE.map(({ key, defaultEnabled }) => [key, defaultEnabled]),
      ) as never,
    });
  });

  it('opts nobody into marketing by default', () => {
    // The old apps sent everything to everyone. Opting in on the user's behalf
    // is how an app gets every notification muted.
    expect(notificationEnabled('offersAndPromotions')).toBe(false);
    expect(notificationEnabled('productNews')).toBe(false);
    expect(notificationEnabled('newShopsNearby')).toBe(false);
  });

  it('keeps booking confirmations on — a booking is not marketing', () => {
    expect(notificationEnabled('bookingConfirmations')).toBe(true);
  });

  it('refuses to let a required category be switched off', () => {
    useNotificationPreferencesStore.getState().set('bookingConfirmations', false);

    expect(notificationEnabled('bookingConfirmations')).toBe(true);
  });

  it('lets an optional category be switched off', () => {
    useNotificationPreferencesStore.getState().set('offersAndPromotions', true);
    expect(notificationEnabled('offersAndPromotions')).toBe(true);

    useNotificationPreferencesStore.getState().set('offersAndPromotions', false);
    expect(notificationEnabled('offersAndPromotions')).toBe(false);
  });

  it('defaults an unknown key to on rather than silently muting', () => {
    // A store restored from an older build will be missing newer keys. Failing
    // closed here means a customer silently stops getting confirmations.
    useNotificationPreferencesStore.setState({ preferences: {} as never });

    expect(notificationEnabled('bookingReminders')).toBe(true);
  });

  it('has a label and a description for every category', () => {
    for (const entry of NOTIFICATION_CATALOGUE) {
      expect(entry.label).toBeTruthy();
      expect(entry.description).toBeTruthy();
    }
  });
});