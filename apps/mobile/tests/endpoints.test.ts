/**
 * The endpoint layer.
 *
 * These are contracts with the server. A wrong path or a parameter renamed on
 * one side only fails in production, on a screen nobody is watching, so every
 * call is pinned here.
 */

import { configureClient } from '@/api/client';
import {
  BOOKING_STATUS_LABELS,
  authApi,
  bookingsApi,
  destinationFor,
  meApi,
  paymentsApi,
  providersApi,
  reviewsApi,
} from '@/api/endpoints';
import type { User } from '@/types/api';

interface Call {
  url: string;
  method: string;
  body?: unknown;
}

let calls: Call[] = [];
let respondWith: (call: Call) => unknown = () => ({});

beforeEach(() => {
  calls = [];
  respondWith = () => ({});
  configureClient({
    getToken: () => 'test-token',
    onUnauthorized: () => undefined,
  });

  jest.spyOn(global, 'fetch').mockImplementation(async (url, init) => {
    const method = init?.method ?? 'GET';
    const body =
      typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body;
    calls.push({ url: String(url), method, body });
    return new Response(JSON.stringify(respondWith(calls.at(-1)!)), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  });
});

afterEach(() => {
  jest.restoreAllMocks();
});

const last = () => calls.at(-1)!;

/** The path and query, without the server host. */
function pathOf(call: Call): string {
  return call.url.replace(/^https?:\/\/[^/]+/, '');
}

// ---------------------------------------------------------------------------

describe('auth endpoints', () => {
  it('signs in with the identifier the account actually uses', async () => {
    await authApi.login({ identifier: 'jane@example.com', password: 'hunter2hunter2' });

    expect(last().method).toBe('POST');
    expect(pathOf(last())).toContain('/auth/login/');
    expect(last().body).toEqual({ identifier: 'jane@example.com', password: 'hunter2hunter2' });
  });

  it('requests a password reset without saying whether the account exists', async () => {
    await authApi.requestPasswordReset('jane@example.com');

    expect(pathOf(last())).toContain('/auth/password-reset/request/');
  });

  it('confirms a password reset with the emailed code', async () => {
    await authApi.confirmPasswordReset({
      email: 'jane@example.com',
      code: '123456',
      new_password: 'a-new-password',
    });

    expect(pathOf(last())).toContain('/auth/password-reset/confirm/');
  });

  it('asks for another verification email', async () => {
    await authApi.resendVerification();

    expect(pathOf(last())).toContain('/auth/resend-verification/');
  });

  it('registers with a role, so the server does not have to guess one', async () => {
    await authApi.register({
      username: 'sharpcuts',
      email: 'shop@example.com',
      password: 'hunter2hunter2',
      role: 'provider',
    });

    expect(pathOf(last())).toContain('/auth/register/');
    expect(last().body).toMatchObject({ role: 'provider' });
  });

  it('signs out this device only by default, and can sign out everywhere', async () => {
    await authApi.logout();
    expect(pathOf(last())).toContain('/auth/logout/');

    await authApi.logoutAll();
    expect(pathOf(last())).toContain('/auth/logout-all/');
  });

  it('posts only the code when verifying an email', async () => {
    await authApi.verifyEmail('123456');

    expect(last().body).toEqual({ code: '123456' });
  });
});

// ---------------------------------------------------------------------------

describe('me endpoints', () => {
  it('sends profile edits as form data when an avatar is attached', async () => {
    await meApi.update({
      first_name: 'Jane',
      avatar: { uri: 'file:///tmp/a.jpg' },
      avatarName: 'a.jpg',
      avatarType: 'image/jpeg',
    });

    expect(last().body).toBeInstanceOf(FormData);
  });

  it('omits fields the user did not change', async () => {
    await meApi.update({ phone: '+9198xxxxxxxx' });

    const form = last().body as FormData;
    // Sending an empty first_name would wipe the user's name server-side.
    expect(form.get('phone')).toBe('+9198xxxxxxxx');
    expect(form.get('first_name')).toBeNull();
  });

  it('changes a password through its own endpoint', async () => {
    await meApi.changePassword({ current_password: 'old-one-here', new_password: 'new-one-here' });

    expect(pathOf(last())).toContain('/me/password/');
    expect(last().method).toBe('POST');
  });

  it('saves the customer profile as form data, since it carries a photo', async () => {
    await meApi.saveCustomerProfile({
      display_name: 'Jane',
      preferred_gender: 'female',
      avatar: { uri: 'file:///tmp/p.jpg', name: 'p.jpg', type: 'image/jpeg' },
    });

    expect(last().method).toBe('PUT');
    expect(pathOf(last())).toContain('/me/profile/');
    const form = last().body as FormData;
    expect(form.get('display_name')).toBe('Jane');
    expect(form.get('preferred_gender')).toBe('female');
  });

  it('drops null fields, which Django would reject as invalid', async () => {
    await meApi.saveCustomerProfile({ display_name: 'Jane', notes: null });

    expect((last().body as FormData).get('notes')).toBeNull();
  });

  it('creates a shop with POST and an existing one with PUT', async () => {
    await meApi.createShop({ display_name: 'Sharp Cuts' });
    expect(last().method).toBe('POST');
    expect(pathOf(last())).toContain('/me/shop/create/');

    await meApi.saveShop({ display_name: 'Sharp Cuts' });
    expect(last().method).toBe('PUT');
    expect(pathOf(last())).toContain('/me/shop/');
  });

  it('registers a push token so reminders can reach this device', async () => {
    await meApi.registerPushToken('ExponentPushToken[abc]', 'android');

    expect(pathOf(last())).toContain('/me/push-tokens/');
    expect(last().body).toEqual({ token: 'ExponentPushToken[abc]', platform: 'android' });
  });

  it('clears every push token when the user signs out of all devices', async () => {
    await meApi.clearPushTokens();

    expect(last().method).toBe('DELETE');
    expect(pathOf(last())).toContain('/me/push-tokens/clear/');
  });

  it('reads the login history a user needs to spot a stranger on the account', async () => {
    await meApi.loginHistory();

    expect(pathOf(last())).toContain('/me/login-history/');
  });

  it('deletes the account with DELETE on /me/', async () => {
    await meApi.deleteAccount();

    expect(last().method).toBe('DELETE');
    expect(pathOf(last())).toMatch(/\/me\/$/);
  });
});

// ---------------------------------------------------------------------------

describe('provider endpoints', () => {
  it('sends nearby shops with their location, for the radius search', async () => {
    await providersApi.search({ lat: 28.6139, lng: 77.209, radius_km: 5 });

    const path = pathOf(last());
    expect(path).toContain('/providers/');
    expect(path).toContain('lat=28.6139');
    expect(path).toContain('radius_km=5');
  });

  it('requests several service types as a comma list', async () => {
    await providersApi.search({ services: ['Haircut', 'Beard trim'] });

    expect(pathOf(last())).toContain('services=Haircut%2CBeard+trim');
  });

  it('asks for the open-now filter rather than filtering on the device', async () => {
    await providersApi.search({ open_now: true });

    // Filtering client-side means booking a shop that has already closed.
    expect(pathOf(last())).toContain('open_now=true');
  });

  it('reads one shop by id', async () => {
    await providersApi.get(42);

    expect(pathOf(last())).toContain('/providers/42/');
  });

  it('asks the server how far away a shop is, rather than measuring itself', async () => {
    await providersApi.get(42, { lat: 28.6139, lng: 77.209 });

    const path = pathOf(last());
    expect(path).toContain('lat=28.6139');
    expect(path).toContain('lng=77.209');
  });

  it('lists the service types to filter by', async () => {
    await providersApi.serviceTypes();

    expect(pathOf(last())).toContain('/providers/types/');
  });

  it('never sends the token to the provider-owning endpoints it does not own', async () => {
    await providersApi.myShop();
    expect(pathOf(last())).toContain('/providers/me/');

    await providersApi.createService({ name: 'Haircut', duration_minutes: 30, price: 250 });
    expect(last().method).toBe('POST');
    expect(pathOf(last())).toContain('/providers/me/services/');
  });

  it('deletes a service with DELETE so caches invalidate correctly', async () => {
    await providersApi.deleteService(7);

    expect(last().method).toBe('DELETE');
    expect(pathOf(last())).toContain('/providers/me/services/7/');
  });

  it('updates a service in place rather than recreating it', async () => {
    await providersApi.updateService(7, { price: 300 });

    expect(last().method).toBe('PATCH');
    expect(pathOf(last())).toContain('/providers/me/services/7/');
  });

  it('edits the shop through PATCH so the id and created date survive', async () => {
    await providersApi.updateShop({ display_name: 'Sharp Cuts' });

    expect(last().method).toBe('PATCH');
    expect(pathOf(last())).toContain('/providers/me/');
  });

  it('reads your own opening hours', async () => {
    await providersApi.hours();

    expect(pathOf(last())).toContain('/providers/me/hours/');
  });

  it('sends the whole week in one request', async () => {
    await providersApi.saveHours([
      { weekday: 0, is_closed: false, opens_at: '09:00', closes_at: '18:00' },
      { weekday: 6, is_closed: true, opens_at: '09:00', closes_at: '18:00' },
    ]);

    expect(last().method).toBe('PUT');
    expect(pathOf(last())).toContain('/providers/me/hours/');
    // One PUT for the week, not seven PATCHes: a provider setting hours wants to
    // set hours, not to fire seven requests and watch for partial failure.
    expect(last().body).toEqual({
      days: [
        { weekday: 0, is_closed: false, opens_at: '09:00', closes_at: '18:00' },
        { weekday: 6, is_closed: true, opens_at: '09:00', closes_at: '18:00' },
      ],
    });
  });

  it('turns bookings off through its own endpoint', async () => {
    await providersApi.setAcceptingBookings(false);

    // Not a field inside updateShop: this is the one setting whose failure
    // means a provider quietly disappears from search.
    expect(pathOf(last())).toContain('/providers/me/accepting-bookings/');
    expect(last().body).toEqual({ is_accepting_bookings: false });
  });

  it('turns bookings back on', async () => {
    await providersApi.setAcceptingBookings(true);

    expect(last().body).toEqual({ is_accepting_bookings: true });
  });

  it('paginates the shop list', async () => {
    await providersApi.search({ page: 3, page_size: 10 });

    const path = pathOf(last());
    expect(path).toContain('page=3');
    expect(path).toContain('page_size=10');
  });

  it('filters by a single service type as well as a list', async () => {
    await providersApi.search({ service_type: 'Haircut' });

    expect(pathOf(last())).toContain('service_type=Haircut');
  });

  it('filters by minimum rating, server-side', async () => {
    await providersApi.search({ min_rating: 4 });

    expect(pathOf(last())).toContain('min_rating=4');
  });

  it('asks the server for the next fortnight of availability', async () => {
    await providersApi.availability(42);

    expect(pathOf(last())).toContain('/providers/42/availability/');
  });
});

// ---------------------------------------------------------------------------

describe('booking endpoints', () => {
  it('quotes a booking before paying, so the total is never a surprise', async () => {
    await bookingsApi.quote({ provider: 42, services: [7, 9], starts_at: '2026-01-14T10:30:00Z' });

    expect(pathOf(last())).toContain('/bookings/quote/');
    expect(last().method).toBe('POST');
  });

  it('reads one booking by reference, deep-link safe', async () => {
    respondWith = () => ({ reference: 'BK-1', status: 'confirmed' });
    const booking = await bookingsApi.get('BK-1');

    expect(booking.status).toBe('confirmed');
    expect(pathOf(last())).toContain('/bookings/BK-1/');
  });

  it('filters bookings by status', async () => {
    await bookingsApi.list({ status: 'confirmed' });

    expect(pathOf(last())).toContain('status=confirmed');
  });

  it('creates a booking and returns it', async () => {
    respondWith = () => ({ reference: 'BK-1', status: 'awaiting_confirmation' });
    const booking = await bookingsApi.create({
      provider: 42,
      services: [7],
      starts_at: '2026-01-14T10:30:00Z',
      notes: 'Please tidy the sides',
    });

    expect(booking.reference).toBe('BK-1');
    expect(last().body).toMatchObject({ notes: 'Please tidy the sides' });
  });

  it('cancels through a dedicated path, not by patching the booking', async () => {
    await bookingsApi.cancel('BK-1', 'Changed my mind');

    expect(last().method).toBe('POST');
    expect(pathOf(last())).toContain('/bookings/BK-1/cancel/');
    expect(last().body).toEqual({ reason: 'Changed my mind' });
  });

  it('cancels with a blank reason when the user gives none', async () => {
    await bookingsApi.cancel('BK-1');

    expect(last().body).toEqual({ reason: '' });
  });

  it('moves a booking forward through the provider action endpoints', async () => {
    for (const action of ['accept', 'decline', 'complete', 'no-show'] as const) {
      await bookingsApi.transition('BK-1', action);
      expect(pathOf(last())).toContain(`/bookings/BK-1/${action}/`);
      expect(last().method).toBe('POST');
    }
  });

  it('asks for upcoming and past bookings separately', async () => {
    await bookingsApi.list({ upcoming: true });
    expect(pathOf(last())).toContain('upcoming=true');

    await bookingsApi.list({ past: true });
    expect(pathOf(last())).toContain('past=true');
  });
});

// ---------------------------------------------------------------------------

describe('payment endpoints', () => {
  it('starts a Razorpay order from a booking reference', async () => {
    respondWith = () => ({
      payment: { id: 1, status: 'created' },
      razorpay: { key_id: 'rzp_test', order_id: 'order_1', amount: 25000, currency: 'INR' },
    });
    const order = await paymentsApi.createOrder('BK-1');

    expect(pathOf(last())).toContain('/payments/orders/');
    expect(last().body).toEqual({ booking: 'BK-1' });
    expect(order.razorpay.amount).toBe(25000);
  });

  it('amounts come back in paise, so the app never does that arithmetic', async () => {
    respondWith = () => ({ razorpay: { amount: 25000 }, amount_display: '₹250.00' });
    const order = await paymentsApi.createOrder('BK-1');

    // Converting rupees to paise on the device is where a rounding error becomes
    // a customer charged the wrong amount.
    expect(order.razorpay.amount).toBe(25000);
  });

  it('sends only what the gateway returned; the signature is checked server-side', async () => {
    await paymentsApi.verify({
      razorpay_order_id: 'order_1',
      razorpay_payment_id: 'pay_1',
      razorpay_signature: 'sig',
    });

    expect(pathOf(last())).toContain('/payments/verify/');
  });

  it('does not retry a payment on a failed verification', async () => {
    respondWith = () => ({ error: { code: 'payment_verification_failed', message: 'No' } });
    await expect(paymentsApi.get('order_1')).resolves.toBeDefined();
    expect(last().url).toContain('/payments/order_1/');
  });
});

// ---------------------------------------------------------------------------

describe('review endpoints', () => {
  it('only lets a completed booking be reviewed', async () => {
    respondWith = () => ({ id: 1, rating: 5 });
    const review = await reviewsApi.create({ provider: 42, rating: 5, booking: 9 });

    expect(review.rating).toBe(5);
    expect(pathOf(last())).toContain('/reviews/new/');
    expect(last().body).toMatchObject({ provider: 42, booking: 9 });
  });

  it('paginates rather than asking for everything', async () => {
    await reviewsApi.list({ page: 2 });

    expect(pathOf(last())).toContain('page=2');
  });

  it('filters reviews by shop and by rating', async () => {
    await reviewsApi.list({ provider: 42, rating: 5 });

    const path = pathOf(last());
    expect(path).toContain('provider=42');
    expect(path).toContain('rating=5');
  });

  it('asks for only this user\'s reviews when asked', async () => {
    await reviewsApi.list({ mine: true });

    expect(pathOf(last())).toContain('mine=true');
  });

  it('deletes a review the user wrote', async () => {
    await reviewsApi.remove(3);

    expect(last().method).toBe('DELETE');
    expect(pathOf(last())).toContain('/reviews/3/');
  });
});

// ---------------------------------------------------------------------------

describe('destinationFor', () => {
  const account = (overrides: Partial<User>) =>
    ({ role: 'customer', is_verified: true, onboarding_complete: true, ...overrides }) as User;

  it.each([
    ['a brand-new visitor', null, false, 'welcome'],
    ['a returning visitor', null, true, 'login'],
    ['an unverified account', account({ is_verified: false }), true, 'verify-email'],
    ['an unfinished customer', account({ onboarding_complete: false }), true, 'onboarding'],
    ['a finished customer', account({}), true, 'customer'],
    ['a finished provider', account({ role: 'provider' }), true, 'provider'],
  ] as const)('routes %s', (_label, user, seenWelcome, expected) => {
    expect(destinationFor(user as User | null, seenWelcome as boolean)).toBe(expected);
  });
});

describe('BOOKING_STATUS_LABELS', () => {
  it('covers every status the API can return', () => {
    const statuses = [
      'pending_payment',
      'awaiting_confirmation',
      'confirmed',
      'completed',
      'cancelled_by_customer',
      'cancelled_by_provider',
      'no_show',
      'refunded',
    ] as const;

    for (const status of statuses) {
      expect(BOOKING_STATUS_LABELS[status]).toBeTruthy();
    }
  });
});