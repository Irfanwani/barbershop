import { buildQuery } from './format';
import type { Page, PriceBand, Provider } from './types';

declare global {
  interface Window {
    /** Set by the dev server or a deploy to point the site at a different API. */
    BARBERSHOP_API_URL?: string;
  }
}

/**
 * Talking to the API.
 *
 * Resolved the same way the no-build version did, because the rule that a
 * dev-server default must not leak to production still holds: on localhost we
 * point at the local API, anywhere else we use a same-origin `/api/v1`, which
 * is what a reverse proxy terminates.
 */
export const API_BASE = (
  (typeof window !== 'undefined' && window.BARBERSHOP_API_URL) ||
  (typeof location !== 'undefined' &&
  (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:8000/api/v1'
    : '/api/v1')
).replace(/\/$/, '');

export const PAGE_SIZE = 10;

export class ApiError extends Error {
  constructor(
    public readonly path: string,
    public readonly status: number,
  ) {
    super(`${path} responded ${status}`);
    this.name = 'ApiError';
  }
}

async function apiGet<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const query = buildQuery(params ?? {});
  const response = await fetch(`${API_BASE}${path}${query ? `?${query}` : ''}`, {
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    throw new ApiError(path, response.status);
  }
  return (await response.json()) as T;
}

export function fetchPrices(): Promise<PriceBand[]> {
  return apiGet<{ bands?: PriceBand[] }>('/providers/prices/').then((body) => body.bands ?? []);
}

export function fetchShops(
  page: number,
  origin: { lat: number; lng: number } | null,
): Promise<Page<Provider>> {
  return apiGet<Page<Provider>>('/providers/', {
    page,
    page_size: PAGE_SIZE,
    ...(origin ? { lat: origin.lat, lng: origin.lng } : {}),
  });
}
