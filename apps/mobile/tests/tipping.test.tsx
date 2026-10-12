/**
 * Tipping.
 *
 * A tip is offered where the review is: on the screen for an appointment that
 * actually happened, immediately after the person sat down and thought about
 * the haircut. Anywhere else it is not offered at all.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import BookingDetailScreen from '../app/(customer)/booking/[reference]';

const mockTipOrder = jest.fn();

jest.mock('@/api/endpoints', () => {
  const actual = jest.requireActual('@/api/endpoints');
  return {
    ...actual,
    BOOKING_STATUS_LABELS: actual.BOOKING_STATUS_LABELS,
    paymentsApi: {
      ...actual.paymentsApi,
      createTipOrder: (...args: unknown[]) => mockTipOrder(...args),
    },
  };
});

jest.mock('expo-router', () => ({
  useLocalSearchParams: () => ({ reference: 'BK-TEST' }),
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
}));

jest.mock('react-native-razorpay', () => ({
  __esModule: true,
  default: { open: jest.fn().mockResolvedValue(undefined) },
}));

function aBooking(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    reference: 'BK-TEST',
    provider: { id: 1, display_name: 'Sharp Cuts Studio', slug: 'sharp-cuts' },
    customer: { id: 2, username: 'sam', display_name: 'Sam' },
    staff: { id: 3, name: 'Ravi', photo: null },
    status: 'completed',
    starts_at: '2026-03-01T10:00:00Z',
    ends_at: '2026-03-01T10:30:00Z',
    duration_minutes: 30,
    subtotal: 20000,
    total: 20200,
    currency: 'INR',
    deposit: 0,
    balance: 0,
    amount_paid: 20200,
    amount_due: 0,
    requires_deposit: false,
    is_paid: true,
    notes: '',
    items: [{ name: 'Haircut', quantity: 1, unit_price: 20000, total: 20000 }],
    can_be_cancelled: false,
    ...overrides,
  };
}

const mockState: { booking: ReturnType<typeof aBooking> } = {
  booking: aBooking(),
};

jest.mock('@/api/hooks', () => {
  const actual = jest.requireActual('@/api/hooks');
  return {
    ...actual,
    useBooking: () => ({ data: mockState.booking, isError: false, refetch: jest.fn() }),
  };
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false, gcTime: 0 }, queries: { retry: false, gcTime: 0 } },
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

beforeEach(() => {
  mockTipOrder.mockReset();
  mockState.booking = aBooking();
});

describe('tipping a finished appointment', () => {
  it('is offered on a completed booking', async () => {
    await render(<BookingDetailScreen />, { wrapper });

    expect(await screen.findByTestId('booking-tip')).toBeOnTheScreen();
  });

  it('is not offered on an appointment that has not happened', async () => {
    mockState.booking = aBooking({ status: 'confirmed', is_paid: false });

    await render(<BookingDetailScreen />, { wrapper });

    await waitFor(() => expect(screen.queryByTestId('booking-review')).toBeNull());
    expect(screen.queryByTestId('booking-tip')).toBeNull();
  });

  it('attributes the tip to the person who did the job', async () => {
    mockTipOrder.mockResolvedValue({
      razorpay: { key_id: 'rzp_test', order_id: 'order_1' },
    });

    await render(<BookingDetailScreen />, { wrapper });
    fireEvent.press(await screen.findByTestId('booking-tip'));
    fireEvent.press(await screen.findByTestId('tip-submit'));

    await waitFor(() => expect(mockTipOrder).toHaveBeenCalledTimes(1));
    // The barber, not the shop: a tip is for the person holding the scissors.
    expect(mockTipOrder).toHaveBeenCalledWith('BK-TEST', 5000, 3);
  });

  it('does not name a barber when the shop itself did the work', async () => {
    mockState.booking = aBooking({ staff: null });
    mockTipOrder.mockResolvedValue({
      razorpay: { key_id: 'rzp_test', order_id: 'order_1' },
    });

    await render(<BookingDetailScreen />, { wrapper });
    fireEvent.press(await screen.findByTestId('booking-tip'));
    fireEvent.press(await screen.findByTestId('tip-submit'));

    await waitFor(() => expect(mockTipOrder).toHaveBeenCalledTimes(1));
    expect(mockTipOrder).toHaveBeenCalledWith('BK-TEST', 5000, undefined);
  });

  it('lets the amount be changed', async () => {
    mockTipOrder.mockResolvedValue({
      razorpay: { key_id: 'rzp_test', order_id: 'order_1' },
    });

    await render(<BookingDetailScreen />, { wrapper });
    fireEvent.press(await screen.findByTestId('booking-tip'));
    fireEvent.press(await screen.findByTestId('tip-amount-10000'));
    fireEvent.press(await screen.findByTestId('tip-submit'));

    await waitFor(() => expect(mockTipOrder).toHaveBeenCalledTimes(1));
    expect(mockTipOrder).toHaveBeenCalledWith('BK-TEST', 10000, 3);
  });
});