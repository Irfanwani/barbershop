/**
 * Retrying must not charge twice, and the key is what stops that.
 *
 * These tests exist because the key used to be generated *inside* the mutation
 * function. React Query calls that function again on every retry, so each
 * attempt sent a fresh key, the server saw an unrelated request each time, and
 * the payment endpoint did the work again. The retry machinery was working
 * exactly as designed and delivering precisely the wrong result.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, renderHook, waitFor } from '@testing-library/react-native';
import type { ReactNode } from 'react';

import { useCreateBooking, useVerifyPayment } from '@/api/hooks';

const mockNewKey = jest.fn();
const mockCreate = jest.fn();
const mockVerify = jest.fn();

jest.mock('@/api/client', () => ({
  ...jest.requireActual('@/api/client'),
  newIdempotencyKey: () => mockNewKey(),
}));

jest.mock('@/api/endpoints', () => ({
  bookingsApi: { create: (...args: unknown[]) => mockCreate(...args) },
  paymentsApi: { verify: (...args: unknown[]) => mockVerify(...args) },
}));

let issued = 0;

beforeEach(() => {
  issued = 0;
  mockNewKey.mockReset();
  mockNewKey.mockImplementation(() => `key-${++issued}`);
  mockCreate.mockReset();
  mockVerify.mockReset();
});

const clients: QueryClient[] = [];

/** One client for the whole test: rebuilding it per render remounts the tree. */
function makeWrapper(retries: number) {
  const client = new QueryClient({
    defaultOptions: {
      mutations: { retry: retries, retryDelay: 0, gcTime: 0 },
      queries: { retry: false, gcTime: 0 },
    },
  });
  clients.push(client);
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

afterEach(() => {
  // React Query keeps timers alive for as long as it holds cached data, and a
  // lingering timer is what stops Jest exiting.
  while (clients.length) clients.pop()?.clear();
  cleanup();
});

const BOOKING = { provider: 1, services: [1], starts_at: '2026-01-01T10:00:00Z' };

const PAYMENT = {
  razorpay_order_id: 'order_1',
  razorpay_payment_id: 'pay_1',
  razorpay_signature: 'sig',
};

describe('the key belongs to the operation, not the attempt', () => {
  it('sends the same key on every retry of one booking', async () => {
    mockCreate.mockRejectedValueOnce(new Error('network down'));
    mockCreate.mockResolvedValueOnce({ reference: 'BK-1' });

    const { result } = await renderHook(() => useCreateBooking(), { wrapper: makeWrapper(1) });

    await result.current
      .mutateAsync(BOOKING)
      .catch(() => undefined);

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(2));
    expect(mockCreate.mock.calls[0][1]).toBe(mockCreate.mock.calls[1][1]);
    expect(mockCreate.mock.calls[0][1]).toMatch(/^key-/);
  });

  it('a fresh booking gets a fresh key', async () => {
    mockCreate.mockResolvedValue({ reference: 'BK-1' });

    const { result } = await renderHook(() => useCreateBooking(), { wrapper: makeWrapper(0) });

    await result.current.mutateAsync(BOOKING);
    await result.current.mutateAsync({ ...BOOKING, services: [2] });

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(2));
    expect(mockCreate.mock.calls[0][1]).not.toBe(mockCreate.mock.calls[1][1]);
  });

  it('a retried payment verify reuses its key', async () => {
    mockVerify.mockRejectedValueOnce(new Error('timeout'));
    mockVerify.mockResolvedValueOnce({ id: 1 });

    const { result } = await renderHook(() => useVerifyPayment(), { wrapper: makeWrapper(1) });

    await result.current.mutateAsync(PAYMENT);

    await waitFor(() => expect(mockVerify).toHaveBeenCalledTimes(2));
    expect(mockVerify.mock.calls[0][1]).toBe(mockVerify.mock.calls[1][1]);
  });

  it('the server sees one operation, not two', async () => {
    mockVerify.mockRejectedValueOnce(new Error('timeout'));
    mockVerify.mockResolvedValueOnce({ id: 1 });

    const { result } = await renderHook(() => useVerifyPayment(), { wrapper: makeWrapper(1) });
    await result.current.mutateAsync(PAYMENT);

    await waitFor(() => expect(mockVerify).toHaveBeenCalledTimes(2));
    const keys = new Set(mockVerify.mock.calls.map((call) => call[1]));
    expect(keys.size).toBe(1);
  });
});