/**
 * WhatsApp, as the customer meets it.
 *
 * The heavy lifting is server-side - one confirmation per booking, replies that
 * cancel - so what is worth testing here is the two places the app could get it
 * wrong: telling somebody they can cancel by reply when there is nothing to
 * cancel, and reading a phone number off somewhere it does not belong.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { render, screen } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import BookingDetailScreen from '../app/(customer)/booking/[reference]';

const mockState: {
  booking: Record<string, unknown>;
  user: { phone: string };
} = { booking: {}, user: { phone: '' } };

jest.mock('@/api/hooks', () => {
  const actual = jest.requireActual('@/api/hooks');
  return {
    ...actual,
    useBooking: () => ({ data: mockState.booking, isError: false, refetch: jest.fn() }),
  };
});

jest.mock('@/store/auth', () => ({
  useAuthStore: (selector: (state: { user: { phone: string } }) => unknown) =>
    selector({ user: mockState.user }),
  useRole: () => 'customer',
}));

jest.mock('expo-router', () => ({
  useLocalSearchParams: () => ({ reference: 'BK-1' }),
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
}));

function aBooking(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    reference: 'BK-1',
    provider: { id: 1, display_name: 'Sharp Cuts Studio' },
    customer: { id: 2, username: 'sam', display_name: 'Sam' },
    staff: null,
    status: 'confirmed',
    starts_at: '2026-03-02T10:00:00Z',
    ends_at: '2026-03-02T10:30:00Z',
    duration_minutes: 30,
    subtotal: 20000,
    platform_fee: 200,
    total: 20200,
    total_display: '₹202',
    currency: 'INR',
    deposit: 10100,
    balance: 10100,
    amount_paid: 10100,
    amount_due: 10100,
    requires_deposit: true,
    notes: '',
    items: [{ name: 'Haircut', quantity: 1, unit_price: 20000, total: 20000 }],
    can_be_cancelled: true,
    ...overrides,
  };
}

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

beforeEach(() => {
  mockState.booking = aBooking();
  mockState.user.phone = '+919876543210';
});

describe('cancelling by WhatsApp reply', () => {
  it('is offered on a booking that can still be cancelled', async () => {
    await render(<BookingDetailScreen />, { wrapper });

    expect(await screen.findByTestId('whatsapp-hint')).toBeOnTheScreen();
  });

  it('is not offered once the booking is cancelled', async () => {
    mockState.booking = aBooking({ status: 'cancelled_by_customer', can_be_cancelled: false });

    await render(<BookingDetailScreen />, { wrapper });

    // Telling somebody they can reply to cancel an appointment they have
    // already cancelled is noise.
    expect(screen.queryByTestId('whatsapp-hint')).toBeNull();
  });

  it('is not offered to somebody with no number on file', async () => {
    mockState.user.phone = '';

    await render(<BookingDetailScreen />, { wrapper });

    expect(screen.queryByTestId('whatsapp-hint')).toBeNull();
  });
});
