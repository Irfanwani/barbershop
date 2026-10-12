/**
 * A shop's opening hours are written in a zone, and it has to be able to say
 * which one.
 *
 * "I open at nine" is a different minute in Bengaluru and in London. The
 * server resolves shop -> account -> server, and the app shows that resolved
 * answer so the shop can see which clock its own hours are being read in rather
 * than guessing.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import type { ReactNode } from 'react';

import AvailabilityScreen from '../app/(provider)/availability';

const mockSaveShop = jest.fn();

const mockState: { shop: Record<string, unknown> } = {
  shop: {
    id: 1,
    display_name: 'Sharp Cuts Studio',
    opening_time: '09:00',
    closing_time: '20:00',
    slot_interval_minutes: 30,
    timezone_name: 'Asia/Kolkata',
    timezone: 'Asia/Kolkata',
    is_accepting_bookings: true,
  },
};

jest.mock('@/api/hooks', () => {
  const actual = jest.requireActual('@/api/hooks');
  return {
    ...actual,
    useMyShop: () => ({ data: mockState.shop }),
    useSaveShop: () => ({ mutateAsync: mockSaveShop, isPending: false }),
    useMyHours: () => ({ data: [] }),
    useSaveHours: () => ({ mutateAsync: jest.fn(), isPending: false }),
    useSetAcceptingBookings: () => ({ mutateAsync: jest.fn(), isPending: false }),
    useAvailability: () => ({ data: { slots: [] } }),
  };
});

jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
}));

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
  mockSaveShop.mockReset();
  mockSaveShop.mockResolvedValue(mockState.shop);
});

describe('shop time zone', () => {
  it('shows the zone its hours are read in', async () => {
    await render(<AvailabilityScreen />, { wrapper });

    expect(await screen.findByText(/hours are read as Asia\/Kolkata/)).toBeOnTheScreen();
  });

  it('shows the resolved zone, not only the one that was set', async () => {
    mockState.shop = {
      ...mockState.shop,
      timezone_name: '',
      timezone: 'Europe/London',
    };

    await render(<AvailabilityScreen />, { wrapper });

    expect(await screen.findByText(/hours are read as Europe\/London/)).toBeOnTheScreen();
  });

  it('saves the zone it was given', async () => {
    await render(<AvailabilityScreen />, { wrapper });

    fireEvent.changeText(await screen.findByTestId('hours-timezone'), 'Europe/London');
    fireEvent.press(await screen.findByTestId('hours-save'));

    await waitFor(() => expect(mockSaveShop).toHaveBeenCalled());
    expect(mockSaveShop.mock.calls[0][0]).toMatchObject({ timezone_name: 'Europe/London' });
  });

  it('clearing it is sent as blank, not as a leftover', async () => {
    await render(<AvailabilityScreen />, { wrapper });

    fireEvent.changeText(await screen.findByTestId('hours-timezone'), '');
    fireEvent.press(await screen.findByTestId('hours-save'));

    await waitFor(() => expect(mockSaveShop).toHaveBeenCalled());
    expect(mockSaveShop.mock.calls[0][0]).toMatchObject({ timezone_name: '' });
  });
});
