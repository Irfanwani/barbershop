import { describe, expect, it } from 'vitest';

import {
  buildQuery,
  describeBand,
  distanceLabel,
  formatPaise,
  haversineMetres,
} from '@/lib/format';

describe('formatPaise', () => {
  it('converts paise to rupees', () => {
    expect(formatPaise(25000)).toBe('₹250.00');
    expect(formatPaise(1)).toBe('₹0.01');
  });

  it('refuses to invent a price', () => {
    // A missing price shown as ₹0.00 is a lie a customer acts on.
    expect(formatPaise(null)).toBe('—');
    expect(formatPaise(undefined)).toBe('—');
    expect(formatPaise(Number.NaN)).toBe('—');
    expect(formatPaise(Number.POSITIVE_INFINITY)).toBe('—');
  });
});

describe('describeBand', () => {
  it('calls a well-populated band typical', () => {
    const copy = describeBand({
      median_display: '₹250.00',
      minimum_display: '₹200.00',
      is_thin: false,
      sample_size: 40,
      p25_display: '₹200.00',
      p75_display: '₹300.00',
    });

    expect(copy?.headline).toBe('Typically ₹250.00');
    expect(copy?.thin).toBe(false);
    expect(copy?.note).toContain('₹200.00');
    expect(copy?.note).toContain('₹300.00');
  });

  it('refuses to call a single shop typical', () => {
    // "Typically ₹250" on the strength of one data point is a confident lie.
    const copy = describeBand({
      median_display: '₹250.00',
      minimum_display: '₹250.00',
      is_thin: true,
      sample_size: 1,
      p25_display: '₹250.00',
      p75_display: '₹250.00',
    });

    expect(copy?.headline).toBe('Prices start around ₹250.00');
    expect(copy?.thin).toBe(true);
    expect(copy?.note).toContain('1 shop —');
  });

  it('pluralises a thin sample correctly', () => {
    const copy = describeBand({
      median_display: '₹250.00',
      minimum_display: '₹250.00',
      is_thin: true,
      sample_size: 2,
      p25_display: '₹250.00',
      p75_display: '₹250.00',
    });
    expect(copy?.note).toContain('2 shops');
  });

  it('returns nothing for a band with no median', () => {
    expect(
      describeBand({
        median_display: null as unknown as string,
        minimum_display: null,
        is_thin: true,
        sample_size: 0,
        p25_display: '—',
        p75_display: '—',
      }),
    ).toBeNull();
  });
});

describe('buildQuery', () => {
  it('drops empty values', () => {
    // ?lat=&lng= can be read as a real zero and sorts everything from Null Island.
    expect(buildQuery({ page: 2, lat: '', lng: null, q: undefined })).toBe('page=2');
  });

  it('encodes values', () => {
    expect(buildQuery({ q: 'hair cut' })).toBe('q=hair+cut');
  });

  it('copes with nothing at all', () => {
    expect(buildQuery({})).toBe('');
  });
});

describe('distance', () => {
  it('measures a known distance', () => {
    // Bengaluru to Mysuru, which is about 128 km as the crow flies.
    const metres = haversineMetres({ lat: 12.9716, lng: 77.5946 }, { lat: 12.2958, lng: 76.6394 });
    expect(metres).toBeGreaterThan(125_000);
    expect(metres).toBeLessThan(132_000);
  });

  it('is zero for the same point', () => {
    expect(haversineMetres({ lat: 1, lng: 1 }, { lat: 1, lng: 1 })).toBe(0);
  });

  it('says nothing when there is no location to measure from', () => {
    expect(distanceLabel(null, { lat: 1, lng: 1 })).toBeNull();
    expect(distanceLabel({ lat: 1, lng: 1 }, null)).toBeNull();
  });

  it('formats a distance for a card', () => {
    expect(distanceLabel({ lat: 12.9716, lng: 77.5946 }, { lat: 12.2958, lng: 76.6394 })).toBe(
      '128.0 km away',
    );
  });
});