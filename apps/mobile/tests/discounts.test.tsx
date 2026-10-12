/**
 * Applying a discount at checkout.
 *
 * The server resolves and prices both of these; the app sends them and renders
 * what comes back. The thing worth testing is that the *booking* carries the
 * same code and points as the quote - a total shown on one screen and a
 * different total charged on the next is the worst version of this bug.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import type { ReactNode } from 'react';

import { BookingSheet } from '@/components/booking-sheet';
import { formatWhen } from '@/components/booking-row';

const mockQuote = jest.fn();
const mockCreate = jest.fn();

jest.mock('@/api/endpoints', () => {
  const actual = jest.requireActual('@/api/endpoints');
  return {
    ...actual,
    bookingsApi: {
      ...actual.bookingsApi,
      quote: (...args: unknown[]) => mockQuote(...args),
      create: (...args: unknown[]) => mockCreate(...args),
    },
  };
});

jest.mock('@/api/hooks', () => {
  const actual = jest.requireActual('@/api/hooks');
  return {
    ...actual,
    useQuote: () => ({ data: mockState.priced, isPending: false, mutateAsync: mockQuote, reset: jest.fn() }),
    usePointsBalance: () => ({ data: mockState.points }),
    useShopStaff: () => ({ data: [] }),
  };
});

jest.mock('expo-router', () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn(), back: jest.fn() }),
}));

const mockState: {
  priced: Record<string, unknown> | undefined;
  points: Record<string, unknown> | undefined;
} = { priced: undefined, points: undefined };

function aQuote(overrides: Record<string, unknown> = {}) {
  return {
    currency: 'INR',
    subtotal: 20000,
    subtotal_display: '₹200',
    platform_fee: 200,
    platform_fee_display: '₹2',
    total: 20200,
    total_display: '₹202',
    deposit_percent: 50,
    deposit: 10100,
    deposit_display: '₹101',
    balance: 10100,
    balance_display: '₹101',
    cancellation_window_hours: 24,
    late_cancel_fee_percent: 0,
    late_cancel_fee: 0,
    late_cancel_fee_display: '₹0',
    duration_minutes: 30,
    starts_at: '2026-03-02T10:00:00Z',
    ends_at: '2026-03-02T10:30:00Z',
    promo_code: null,
    promo_description: '',
    points_spent: 0,
    points_worth_minor: 0,
    items: [
      {
        service_id: 1,
        name: 'Haircut',
        unit_price: 20000,
        unit_price_display: '₹200',
        duration_minutes: 30,
      },
    ],
    is_available: true,
    ...overrides,
  };
}

const SERVICE = {
  id: 1,
  name: 'Haircut',
  price: 20000,
  price_display: '₹200',
  duration_minutes: 30,
  is_active: true,
};

const PROVIDER = {
  id: 1,
  display_name: 'Sharp Cuts Studio',
  slug: 'sharp-cuts',
  services: [SERVICE],
} as never;

const SLOT = '2026-03-02T10:00:00Z';

const AVAILABILITY = {
  date: '2026-03-02',
  slots: [{ starts_at: SLOT, is_available: true }],
} as never;

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: {
      mutations: { retry: false, gcTime: 0 },
      queries: { retry: false, gcTime: 0 },
    },
  });
  return (
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 47, left: 0, right: 0, bottom: 34 },
      }}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </SafeAreaProvider>
  );
}

async function openSheet() {
  await render(
    <BookingSheet visible onClose={jest.fn()} provider={PROVIDER} availability={AVAILABILITY} />,
    { wrapper },
  );
  fireEvent.press(await screen.findByTestId('book-service-1'));
  fireEvent.press(await screen.findByText(formatWhen(SLOT)));
}

beforeEach(() => {
  mockQuote.mockReset();
  mockCreate.mockReset();
  mockCreate.mockResolvedValue({ reference: 'BK-1' });
  mockState.priced = aQuote();
  mockState.points = undefined;
});

describe('promo codes', () => {
  it('sends the code to be resolved, never a discount', async () => {
    await openSheet();

    fireEvent.changeText(await screen.findByTestId('promo-code'), 'WELCOME10');
    fireEvent.press(await screen.findByTestId('promo-apply'));

    await waitFor(() => expect(mockQuote).toHaveBeenCalled());
    expect(mockQuote.mock.calls.at(-1)?.[0]).toMatchObject({
      promo_code: 'WELCOME10',
    });
  });

  it('omits it entirely when the field is empty', async () => {
    await openSheet();

    fireEvent.press(await screen.findByTestId('promo-apply'));

    await waitFor(() => expect(mockQuote).toHaveBeenCalled());
    expect(mockQuote.mock.calls.at(-1)?.[0]).not.toHaveProperty('promo_code');
  });

  it('says the code was understood', async () => {
    mockState.priced = aQuote({ promo_code: 'WELCOME10', promo_description: '10% off' });
    await openSheet();

    expect(await screen.findByText('10% off')).toBeOnTheScreen();
  });

  it('carries the code into the booking', async () => {
    await openSheet();

    fireEvent.changeText(await screen.findByTestId('promo-code'), 'WELCOME10');
    fireEvent.press(await screen.findByTestId('promo-apply'));
    await waitFor(() => expect(mockQuote).toHaveBeenCalled());
    fireEvent.press(await screen.findByTestId('book-confirm'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate.mock.calls[0][0]).toMatchObject({ promo_code: 'WELCOME10' });
  });
});

describe('loyalty points', () => {
  it('is not offered to somebody with no points', async () => {
    mockState.points = { available: 0, expiring_soon: 0, worth_minor: 0 };
    await openSheet();

    expect(await screen.findByTestId('promo-code')).toBeOnTheScreen();
    expect(screen.queryByTestId('points-toggle')).toBeNull();
  });

  it('offers the balance and what it is worth', async () => {
    mockState.points = { available: 120, expiring_soon: 0, worth_minor: 12000 };
    await openSheet();

    expect(await screen.findByText('Use my 120 points')).toBeOnTheScreen();
  });

  it('warns about points about to expire', async () => {
    mockState.points = { available: 120, expiring_soon: 40, worth_minor: 12000 };
    await openSheet();

    expect(await screen.findByText(/40 expiring soon/)).toBeOnTheScreen();
  });

  it('asks the server what they are worth rather than deciding', async () => {
    mockState.points = { available: 120, expiring_soon: 0, worth_minor: 12000 };
    await openSheet();

    fireEvent.press(await screen.findByTestId('points-toggle'));

    await waitFor(() => expect(mockQuote).toHaveBeenCalled());
    expect(mockQuote.mock.calls.at(-1)?.[0]).toMatchObject({ redeem_points: 120 });
  });

  it('sends nothing when the customer declines', async () => {
    mockState.points = { available: 120, expiring_soon: 0, worth_minor: 12000 };
    await openSheet();

    fireEvent.press(await screen.findByTestId('promo-apply'));

    await waitFor(() => expect(mockQuote).toHaveBeenCalled());
    expect(mockQuote.mock.calls.at(-1)?.[0]).not.toHaveProperty('redeem_points');
  });

  it('carries them into the booking', async () => {
    mockState.points = { available: 120, expiring_soon: 0, worth_minor: 12000 };
    await openSheet();

    fireEvent.press(await screen.findByTestId('points-toggle'));
    await waitFor(() => expect(mockQuote).toHaveBeenCalled());
    fireEvent.press(await screen.findByTestId('book-confirm'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate.mock.calls[0][0]).toMatchObject({ redeem_points: 120 });
  });
});