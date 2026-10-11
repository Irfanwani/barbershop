import { QueryClient } from '@tanstack/react-query';

import { ApiError } from '@/api/client';

/**
 * Query defaults, tuned for a mobile client on a phone connection.
 *
 * `retry` deliberately does not retry 4xx. A 400 means the request is wrong and
 * will be wrong again; retrying it just delays the error the user needs to see.
 * A 5xx or a dropped connection is worth another go.
 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError) {
    if (error.status >= 400 && error.status < 500) return false;
  }
  return failureCount < 2;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export const queryClient = createQueryClient();

/** Query keys, in one place so a typo cannot silently split a cache. */
export const keys = {
  me: ['me'] as const,
  customerProfile: ['me', 'customer-profile'] as const,
  shop: ['providers', 'me'] as const,
  services: ['providers', 'me', 'services'] as const,
  hours: ['providers', 'me', 'hours'] as const,
  payout: ['providers', 'me', 'payout'] as const,
  balance: ['providers', 'me', 'balance'] as const,
  ledger: ['providers', 'me', 'ledger'] as const,
  serviceTypes: ['providers', 'types'] as const,
  priceBands: ['providers', 'prices'] as const,
  servicePrices: ['providers', 'prices', 'services'] as const,
  providers: (params?: unknown) => ['providers', 'list', params ?? {}] as const,
  provider: (id: number | string) => ['providers', 'detail', id] as const,
  availability: (id: number | string, days?: number) =>
    ['providers', 'availability', id, days ?? 14] as const,
  bookings: (params?: unknown) => ['bookings', 'list', params ?? {}] as const,
  booking: (reference: string) => ['bookings', 'detail', reference] as const,
  reviews: (params?: unknown) => ['reviews', 'list', params ?? {}] as const,
  quote: ['bookings', 'quote'] as const,
  products: (params?: unknown) => ['products', 'list', params ?? {}] as const,
  product: (id: number | string) => ['products', 'detail', id] as const,
  popular: ['products', 'popular'] as const,
  categories: ['products', 'types'] as const,
  shopShelf: (id: number | string, params?: unknown) =>
    ['products', 'shelf', id, params ?? {}] as const,
  myShelf: ['products', 'my-shelf'] as const,
  myOrders: (params?: unknown) => ['orders', 'mine', params ?? {}] as const,
  shopOrders: (params?: unknown) => ['orders', 'shop', params ?? {}] as const,
  order: (reference: string) => ['orders', 'detail', reference] as const,
  orderQuote: (provider: number) => ['orders', 'quote', provider] as const,
};