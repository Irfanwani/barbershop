/**
 * Booking a run of visits.
 *
 * The thing worth protecting is that the app never works out the later dates.
 * It sends an interval and a count; the server derives every date from the
 * first one. A client that did the arithmetic itself would put two visits in
 * the same week the first time somebody's phone disagreed about the length of
 * a month.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import { BookingSheet } from '@/components/booking-sheet';
import { formatWhen } from '@/components/booking-row';

const mockQuote = jest.fn();
const mockCreate = jest.fn();
const mockCreateSeries = jest.fn();

const mockState: { priced: Record<string, unknown> | undefined } = { priced: undefined };

jest.mock('@/api/endpoints', () => {
  const actual = jest.requireActual('@/api/endpoints');
  return {
    ...actual,
    bookingsApi: {
      ...actual.bookingsApi,
      quote: (...args: unknown[]) => mockQuote(...args),
      create: (...args: unknown[]) => mockCreate(...args),
    },
    seriesApi: {
      ...actual.seriesApi,
      create: (...args: unknown[]) => mockCreateSeries(...args),
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
  };
});

const mockReplace = jest.fn();
jest.mock('expo-router', () => ({
  useRouter: () => ({ replace: mockReplace, push: jest.fn(), back: jest.fn() }),
}));

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
        name: 'Beard trim',
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
      name: 'Beard trim',
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
  mockCreateSeries.mockReset();
  mockReplace.mockReset();
  mockCreate.mockResolvedValue({ reference: 'BK-1' });
  mockCreateSeries.mockResolvedValue({ id: 1, starts_at: SLOT });
  mockState.priced = aQuote();
});

describe('regular visits', () => {
  it('is not offered unless asked for', async () => {
    await openSheet();

    expect(await screen.findByTestId('repeat-toggle')).toBeOnTheScreen();
    expect(screen.queryByTestId('interval-28')).toBeNull();
  });

  it('a single visit books exactly one appointment', async () => {
    await openSheet();

    fireEvent.press(await screen.findByTestId('book-confirm'));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreateSeries).not.toHaveBeenCalled();
  });

  it('the interval choices appear once it is turned on', async () => {
    await openSheet();

    fireEvent.press(await screen.findByTestId('repeat-toggle'));

    expect(await screen.findByTestId('interval-28')).toBeOnTheScreen();
    expect(screen.getByTestId('visits-6')).toBeOnTheScreen();
  });

  it('sends the interval and the count, and no dates of its own', async () => {
    await openSheet();
    fireEvent.press(await screen.findByTestId('repeat-toggle'));
    fireEvent.press(await screen.findByTestId('interval-42'));
    fireEvent.press(await screen.findByTestId('visits-4'));
    fireEvent.press(await screen.findByTestId('book-confirm'));

    await waitFor(() => expect(mockCreateSeries).toHaveBeenCalledTimes(1));
    expect(mockCreateSeries.mock.calls[0][0]).toEqual({
      provider: 1,
      services: [1],
      starts_at: SLOT,
      interval_days: 42,
      total_occurrences: 4,
    });
    // The server derives the rest. A client-sent date list is how two visits
    // end up in the same week.
    expect(mockCreateSeries.mock.calls[0][0]).not.toHaveProperty('dates');
  });

  it('defaults to every four weeks, which is what most people mean', async () => {
    await openSheet();
    fireEvent.press(await screen.findByTestId('repeat-toggle'));
    fireEvent.press(await screen.findByTestId('book-confirm'));

    await waitFor(() => expect(mockCreateSeries).toHaveBeenCalledTimes(1));
    expect(mockCreateSeries.mock.calls[0][0].interval_days).toBe(28);
  });

  it('books a series rather than a single booking', async () => {
    await openSheet();
    fireEvent.press(await screen.findByTestId('repeat-toggle'));
    fireEvent.press(await screen.findByTestId('book-confirm'));

    await waitFor(() => expect(mockCreateSeries).toHaveBeenCalledTimes(1));
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('says the visits are paid for separately', async () => {
    await openSheet();
    fireEvent.press(await screen.findByTestId('repeat-toggle'));

    expect(await screen.findByText(/paid for on its own/)).toBeOnTheScreen();
  });
});
