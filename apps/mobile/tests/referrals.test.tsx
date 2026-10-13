/**
 * Referrals, from the customer's side.
 *
 * Two halves that are easy to get wrong together: the code has to be
 * *shareable*, and it has to be *enterable*. A referral scheme with only the
 * first is a scheme nobody uses.
 *
 * The thing worth pinning down is what the app does and does not decide. It
 * sends the code; it never works out whether the code is good, who it pays, or
 * when. All of that is the server's, because all of it is worth money.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Share } from 'react-native';
import type { ReactNode } from 'react';

import { BookingSheet } from '@/components/booking-sheet';
import CustomerBookings from '../app/(customer)/bookings';
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
    useQuote: () => ({
      data: mockState.priced,
      isPending: false,
      mutateAsync: mockQuote,
      reset: jest.fn(),
    }),
    usePointsBalance: () => ({ data: undefined }),
    useConsultationPrompt: () => ({ data: { forms: [], questions: [] } }),
    useShopStaff: () => ({ data: [] }),
    useMyReferrals: () => ({ data: mockState.referrals }),
    useMySeries: () => ({ data: [] }),
    useStopSeries: () => ({ mutateAsync: jest.fn(), isPending: false }),
  };
});

jest.mock('expo-router', () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({}),
}));

const mockState: {
  priced: Record<string, unknown> | undefined;
  referrals: Record<string, unknown> | undefined;
} = { priced: undefined, referrals: undefined };

function aQuote() {
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
  };
}

const SLOT = '2026-03-02T10:00:00Z';

const PROVIDER = {
  id: 1,
  display_name: 'Sharp Cuts Studio',
  slug: 'sharp-cuts',
  services: [
    {
      id: 1,
      name: 'Haircut',
      price: 20000,
      price_display: '₹200',
      duration_minutes: 30,
      is_active: true,
    },
  ],
} as never;

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
  mockState.referrals = {
    code: 'ACDE2345',
    given: [],
    given_count: 0,
    rewarded_count: 0,
    referred_by: null,
  };
  jest.spyOn(Share, 'share').mockResolvedValue({ action: 'sharedAction' });
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('entering somebody else\'s code', () => {
  it('sends nothing when the field is empty', async () => {
    await openSheet();

    fireEvent.press(await screen.findByTestId('book-confirm'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate.mock.calls[0][0]).not.toHaveProperty('referral_code');
  });

  it('sends the code, upper-cased', async () => {
    await openSheet();

    fireEvent.changeText(await screen.findByTestId('referral-code'), 'acde2345');
    fireEvent.press(await screen.findByTestId('book-confirm'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate.mock.calls[0][0].referral_code).toBe('ACDE2345');
  });

  it('says when the credit actually lands', async () => {
    await openSheet();

    expect(await screen.findByText(/when your appointment is done/)).toBeOnTheScreen();
  });
});

describe('sharing your own code', () => {
  it('shows it', async () => {
    await render(<CustomerBookings />, { wrapper });

    expect(await screen.findByTestId('my-referral-code')).toBeOnTheScreen();
    expect(screen.getByText('ACDE2345')).toBeOnTheScreen();
  });

  it('does not appear when there is no code', async () => {
    mockState.referrals = undefined;

    await render(<CustomerBookings />, { wrapper });

    expect(screen.queryByTestId('my-referral-code')).toBeNull();
  });

  it('shares it with a plain-text message', async () => {
    await render(<CustomerBookings />, { wrapper });
    fireEvent.press(await screen.findByTestId('share-referral-code'));

    await waitFor(() => expect(Share.share).toHaveBeenCalled());
    const message = (Share.share as jest.Mock).mock.calls[0][0].message as string;
    expect(message).toContain('ACDE2345');
    // Links and cards are not the point; the code has to survive being pasted
    // into a message.
    expect(message).not.toContain('http');
  });

  it('reports how many people have used it', async () => {
    mockState.referrals = {
      code: 'ACDE2345',
      given: [
        { referred_display_name: 'Sam', status: 'rewarded', provider: 'Sharp Cuts', rewarded_at: null },
      ],
      given_count: 1,
      rewarded_count: 1,
      referred_by: null,
    };

    await render(<CustomerBookings />, { wrapper });

    expect(await screen.findByText(/1 person has used it/)).toBeOnTheScreen();
  });

  it('is not shown to somebody who was referred themselves as an offer', async () => {
    mockState.referrals = {
      code: 'ACDE2345',
      given: [],
      given_count: 0,
      rewarded_count: 0,
      referred_by: 'Priya',
    };

    await render(<CustomerBookings />, { wrapper });

    // The code is still shareable, but the copy must not claim they got there
    // through somebody else.
    expect(screen.queryByText(/booked with this code/i)).toBeNull();
  });
});
