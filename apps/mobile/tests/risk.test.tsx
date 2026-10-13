/**
 * The provider's view of a customer.
 *
 * The one thing worth protecting: this screen is advice, and it says so. A
 * panel that looked like a verdict would be one providers either obey blindly
 * or stop opening. The tests are mostly about it saying the right thing, and
 * saying it in the cases where saying nothing is the honest answer.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { fireEvent, render, screen } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import { CustomerRiskSheet } from '@/components/customer-risk-sheet';

const mockClear = jest.fn();

const mockState: { risk: Record<string, unknown> | undefined } = { risk: undefined };

jest.mock('@/api/hooks', () => {
  const actual = jest.requireActual('@/api/hooks');
  return {
    ...actual,
    useCustomerRisk: () => ({ data: mockState.risk, isError: false }),
    useClearRiskFlag: () => ({ mutateAsync: mockClear, isPending: false }),
  };
});

function aRisk(overrides: Record<string, unknown> = {}) {
  return {
    total_bookings: 5,
    completed: 3,
    no_shows: 2,
    cancelled: 0,
    no_show_rate: 0.4,
    cancel_rate: 0,
    risk_level: 'medium',
    suggested_deposit_percent: 50,
    advisory: true,
    flags: [
      {
        id: 9,
        kind: 'repeat_no_show',
        severity: 'medium',
        reason: '2 no-shows out of 5 appointments',
        raised_at: '2026-03-01T10:00:00Z',
      },
    ],
    customer_display_name: 'Sam',
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

function open() {
  return render(
    <CustomerRiskSheet customerId={2} displayName="Sam" onClose={jest.fn()} />,
    { wrapper },
  );
}

beforeEach(() => {
  mockClear.mockReset();
  mockState.risk = aRisk();
});

describe('a customer with a poor record', () => {
  it('shows the record in words', async () => {
    await open();

    expect(await screen.findByText(/2 not turned up to/)).toBeOnTheScreen();
  });

  it('suggests a deposit', async () => {
    await open();

    expect(await screen.findByText('50%')).toBeOnTheScreen();
  });

  it('says the suggestion is not a price', async () => {
    await open();

    expect(await screen.findByText(/does not change what the customer/)).toBeOnTheScreen();
  });

  it('shows the flag and what it says', async () => {
    await open();

    expect(await screen.findByText('2 no-shows out of 5 appointments')).toBeOnTheScreen();
  });

  it('can be forgiven', async () => {
    mockClear.mockResolvedValue({ id: 9, cleared: true });

    await open();
    fireEvent.press(await screen.findByTestId('clear-flag-9'));

    expect(mockClear).toHaveBeenCalledWith(9);
  });
});

describe('a customer with no history', () => {
  it('is not shown as risky', async () => {
    mockState.risk = aRisk({
      total_bookings: 0,
      completed: 0,
      no_shows: 0,
      no_show_rate: 0,
      cancel_rate: 0,
      risk_level: null,
      suggested_deposit_percent: null,
      flags: [],
    });

    await open();

    // "Unknown" must not render as "fine" or as "risky" - it is neither, and
    // collapsing it into one of those is how every new customer ends up needing
    // a deposit.
    expect(await screen.findByText(/No history here to judge/)).toBeOnTheScreen();
    expect(screen.queryByTestId('risk-level')).toBeNull();
    expect(screen.queryByText('50%')).toBeNull();
  });

  it('says they have no appointments here', async () => {
    mockState.risk = aRisk({ total_bookings: 0, risk_level: null, flags: [] });

    await open();

    expect(await screen.findByText(/No appointments here yet/)).toBeOnTheScreen();
  });
});

describe('a clean record', () => {
  it('is not shown as risky either', async () => {
    mockState.risk = aRisk({
      total_bookings: 12,
      completed: 12,
      no_shows: 0,
      no_show_rate: 0,
      risk_level: null,
      suggested_deposit_percent: null,
      flags: [],
    });

    await open();

    expect(screen.queryByTestId('risk-level')).toBeNull();
    // Not "no history" - they have twelve of them. Nothing here stands out,
    // which is a different sentence from knowing nothing.
    expect(await screen.findByText(/Nothing here stands out/)).toBeOnTheScreen();
    expect(screen.queryByText(/No history here to judge/)).toBeNull();
  });
});
