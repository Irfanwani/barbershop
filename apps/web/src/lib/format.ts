import type { ApproximateLocation, Origin, PriceBand } from './types';

/**
 * Pure helpers for the marketing site.
 *
 * No fetch, no DOM, no side effects: everything here is a function of its
 * arguments, which is what makes it worth testing directly.
 */

/**
 * Paise to a rupee string.
 *
 * Returns an em dash rather than "₹NaN" or "₹0.00" for anything that is not a
 * finite number, because a missing price displayed as ₹0.00 is a lie a
 * customer acts on.
 */
export function formatPaise(minor: number | null | undefined): string {
  if (typeof minor !== 'number' || !Number.isFinite(minor)) return '—';
  return `₹${(minor / 100).toFixed(2)}`;
}

/**
 * What to say about a price band.
 *
 * A median across one shop is not a median, it is that shop's price. Saying
 * "typically ₹250" on the strength of a single data point is a confident lie,
 * so a thin sample is described as a starting point instead of a rate.
 */
export function describeBand(band: Pick<
  PriceBand,
  'median_display' | 'minimum_display' | 'is_thin' | 'sample_size' | 'p25_display' | 'p75_display'
>): { headline: string; note: string; thin: boolean } | null {
  if (!band || !band.median_display) return null;

  if (band.is_thin) {
    const count = band.sample_size;
    return {
      headline: `Prices start around ${band.minimum_display ?? band.median_display}`,
      note: `Based on ${count} ${count === 1 ? 'shop' : 'shops'} — a rough guide, not a going rate.`,
      thin: true,
    };
  }

  return {
    headline: `Typically ${band.median_display}`,
    note: `Most fall between ${band.p25_display} and ${band.p75_display} · from ${band.sample_size} shops`,
    thin: false,
  };
}

/**
 * Build a query string, dropping anything empty.
 *
 * Sends `?lat=&lng=` otherwise, which a server may read as a real zero and
 * happily sort every shop by distance from Null Island.
 */
export function buildQuery(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  return search.toString();
}

const EARTH_RADIUS_METRES = 6_371_000;

export function toRad(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

/** Great-circle distance, for showing "1.2 km away" before the server sorts. */
export function haversineMetres(
  a: ApproximateLocation | Origin,
  b: ApproximateLocation | Origin,
): number {
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return Math.round(
    EARTH_RADIUS_METRES * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h)),
  );
}

/** "1.2 km away", or null when there is no location to measure from. */
export function distanceLabel(
  origin: Origin | null,
  location: ApproximateLocation | null,
): string | null {
  if (!origin || !location) return null;
  const metres = haversineMetres(origin, location);
  if (!Number.isFinite(metres)) return null;
  return `${(metres / 1000).toFixed(1)} km away`;
}