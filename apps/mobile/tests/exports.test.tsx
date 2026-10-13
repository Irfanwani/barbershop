/**
 * Asking for a spreadsheet.
 *
 * The screen's real job is explaining the wait. A year of bookings is built by
 * a worker and emailed, and a button that returns nothing for two minutes is a
 * button people press four times.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import ProviderExports from '../app/(provider)/exports';

const mockRequest = jest.fn();

const mockState: { rows: Record<string, unknown>[] } = { rows: [] };

jest.mock('@/api/hooks', () => {
  const actual = jest.requireActual('@/api/hooks');
  return {
    ...actual,
    useExports: () => ({ data: mockState.rows, isLoading: false }),
    useRequestExport: () => ({ mutateAsync: mockRequest, isPending: false }),
  };
});

function aRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    from_date: '2026-01-01',
    to_date: '2026-03-01',
    datasets: ['bookings', 'revenue'],
    status: 'sent',
    row_count: 250,
    failure_reason: '',
    created_at: '2026-03-02T10:00:00Z',
    sent_at: '2026-03-02T10:00:05Z',
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
  mockRequest.mockReset();
  mockRequest.mockResolvedValue(aRow({ status: 'queued' }));
  mockState.rows = [];
});

describe('asking for an export', () => {
  it('says it emails rather than downloads', async () => {
    await render(<ProviderExports />, { wrapper });

    // A shop needs to know why there is no download button before they look for
    // one.
    expect(await screen.findByText(/We email you the files/)).toBeOnTheScreen();
  });

  it('says every appointment comes out, not just a page', async () => {
    await render(<ProviderExports />, { wrapper });

    expect(await screen.findByText(/not just the ones on the first page/)).toBeOnTheScreen();
  });

  it('sends the chosen period', async () => {
    await render(<ProviderExports />, { wrapper });

    fireEvent.press(await screen.findByTestId('period-30'));
    fireEvent.press(await screen.findByTestId('request-export'));

    await waitFor(() => expect(mockRequest).toHaveBeenCalledTimes(1));
    const body = mockRequest.mock.calls[0][0] as { from_date: string; to_date: string };
    const from = new Date(body.from_date);
    const to = new Date(body.to_date);
    const spanDays = Math.round((to.getTime() - from.getTime()) / 86_400_000);
    expect(spanDays).toBe(30);
  });

  it('sends the chosen datasets', async () => {
    await render(<ProviderExports />, { wrapper });

    fireEvent.press(await screen.findByTestId('period-365'));
    fireEvent.press(await screen.findByTestId('request-export'));

    await waitFor(() => expect(mockRequest).toHaveBeenCalledTimes(1));
    expect(mockRequest.mock.calls[0][0].datasets).toEqual(['bookings', 'revenue']);
  });

  it('can add another dataset', async () => {
    await render(<ProviderExports />, { wrapper });

    fireEvent.press(await screen.findByTestId('dataset-clients'));
    fireEvent.press(await screen.findByTestId('request-export'));

    await waitFor(() => expect(mockRequest).toHaveBeenCalledTimes(1));
    expect(mockRequest.mock.calls[0][0].datasets).toContain('clients');
  });

  it('will not send nothing', async () => {
    await render(<ProviderExports />, { wrapper });

    fireEvent.press(await screen.findByTestId('dataset-bookings'));
    fireEvent.press(await screen.findByTestId('dataset-revenue'));
    fireEvent.press(await screen.findByTestId('request-export'));

    await waitFor(() => expect(screen.getByText(/at least one thing/)).toBeOnTheScreen());
    expect(mockRequest).not.toHaveBeenCalled();
  });
});

describe('previous exports', () => {
  it('are listed with how many rows came out', async () => {
    mockState.rows = [aRow()];

    await render(<ProviderExports />, { wrapper });

    expect(await screen.findByText(/250 rows/)).toBeOnTheScreen();
    expect(screen.getByTestId('export-status-1')).toBeOnTheScreen();
  });

  it('say when one failed and why', async () => {
    mockState.rows = [
      aRow({ status: 'failed', row_count: 0, failure_reason: 'The email could not be sent.' }),
    ];

    await render(<ProviderExports />, { wrapper });

    // A failure nobody is told about is one that gets repeated.
    expect(await screen.findByText('The email could not be sent.')).toBeOnTheScreen();
  });

  it('explain a wait rather than showing nothing', async () => {
    mockState.rows = [aRow({ status: 'queued', row_count: 0 })];

    await render(<ProviderExports />, { wrapper });

    expect(await screen.findByText('On its way')).toBeOnTheScreen();
  });
});
