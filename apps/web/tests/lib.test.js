/**
 * The pure rendering and formatting helpers.
 *
 * These take values and return strings, which makes them the cheapest thing in
 * the codebase to test and the easiest thing to get subtly wrong.
 */

import {
  buildQuery,
  describeBand,
  escapeHtml,
  formatPaise,
  haversineMetres,
  renderPrices,
  shopCard,
} from '../lib.js';
import { band, provider } from './setup.js';

describe('escapeHtml', () => {
  it('escapes everything that could start a tag or an attribute', () => {
    expect(escapeHtml('<script>alert("x")</script>')).toBe(
      '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;',
    );
  });

  it('escapes an ampersand before anything else', () => {
    // Escaping `&` last would turn `&lt;` into `&amp;lt;`.
    expect(escapeHtml('a & <b>')).toBe('a &amp; &lt;b&gt;');
  });

  it('escapes single quotes, which break out of an attribute', () => {
    expect(escapeHtml("it's")).toBe('it&#39;s');
  });

  it('treats null and undefined as empty', () => {
    expect(escapeHtml(null)).toBe('');
    expect(escapeHtml(undefined)).toBe('');
  });
});

describe('formatPaise', () => {
  it('converts paise to rupees', () => {
    expect(formatPaise(25000)).toBe('₹250.00');
  });

  it('keeps the paisa', () => {
    expect(formatPaise(25050)).toBe('₹250.50');
  });

  it('refuses to show a price it does not have', () => {
    // ₹0.00 is a price. Displaying a missing one as zero is a number a
    // customer acts on.
    expect(formatPaise(null)).toBe('—');
    expect(formatPaise(undefined)).toBe('—');
    expect(formatPaise('300')).toBe('—');
    expect(formatPaise(Number.NaN)).toBe('—');
  });
});

describe('describeBand', () => {
  it('says "typically" when the sample is big enough', () => {
    const copy = describeBand(band({ is_thin: false, sample_size: 12 }));

    expect(copy.headline).toBe('Typically ₹300.00');
    expect(copy.thin).toBe(false);
  });

  it('does not say "typically" on the strength of one shop', () => {
    // A median of one shop is not a median, it is that shop's price.
    const copy = describeBand(band({ is_thin: true, sample_size: 1 }));

    expect(copy.headline).not.toContain('Typically');
    expect(copy.headline).toContain('start around');
    expect(copy.thin).toBe(true);
  });

  it('says how few shops it is based on', () => {
    expect(describeBand(band({ is_thin: true, sample_size: 2 })).note).toContain('2 shops');
    expect(describeBand(band({ is_thin: true, sample_size: 1 })).note).toContain('1 shop');
  });

  it('returns nothing for a band with no median', () => {
    expect(describeBand({ ...band(), median_display: null })).toBeNull();
    expect(describeBand(null)).toBeNull();
  });
});

describe('buildQuery', () => {
  it('drops empty values rather than sending ?a=', () => {
    expect(buildQuery({ lat: 28.6, lng: undefined, radius: null, name: '', open: false })).toBe(
      'lat=28.6&open=false',
    );
  });

  it('keeps zero, which is a real value', () => {
    expect(buildQuery({ page: 0 })).toBe('page=0');
  });

  it('returns nothing for no parameters', () => {
    expect(buildQuery({})).toBe('');
    expect(buildQuery(null)).toBe('');
  });
});

describe('haversineMetres', () => {
  it('is zero for the same point', () => {
    const delhi = { lat: 28.6139, lng: 77.209 };
    expect(haversineMetres(delhi, delhi)).toBe(0);
  });

  it('matches a known distance', () => {
    // Connaught Place to India Gate, roughly 3.7 km.
    const metres = haversineMetres(
      { lat: 28.6139, lng: 77.209 },
      { lat: 28.6129, lng: 77.2295 },
    );
    expect(Math.round(metres / 100) / 10).toBeGreaterThan(1.5);
    expect(metres).toBeLessThan(5000);
  });

  it('says nothing rather than guessing when a point is missing', () => {
    expect(haversineMetres(null, { lat: 1, lng: 1 })).toBeNull();
    expect(haversineMetres({ lat: 1, lng: 1 }, undefined)).toBeNull();
  });
});

describe('renderPrices', () => {
  it('renders one card per band', () => {
    const html = renderPrices([band(), band({ service_type_label: 'Spa' })]);

    expect(html).toContain('Barber shop');
    expect(html).toContain('Spa');
  });

  it('skips a band it has nothing to say about', () => {
    expect(renderPrices([{ ...band(), median_display: null }])).toContain('Not enough prices');
  });

  it('marks a thin sample in the markup, not just in the text', () => {
    const html = renderPrices([band({ is_thin: true, sample_size: 1 })]);

    expect(html).toContain('is-thin');
  });

  it('copes with no bands at all', () => {
    expect(renderPrices(undefined)).toContain('Not enough prices');
  });
});

describe('shopCard', () => {
  it('shows the price when the shop is taking bookings', () => {
    expect(shopCard(provider())).toContain('₹250.00');
  });

  it('does not advertise a price when the shop is closed', () => {
    const html = shopCard(provider({ is_accepting_bookings: false }));

    expect(html).not.toContain('₹250.00');
    expect(html).toContain('Not taking bookings');
  });

  it('says no reviews rather than showing a bare zero', () => {
    const html = shopCard(provider({ rating_count: 0 }));

    expect(html).toContain('No reviews yet');
    expect(html).not.toContain('0 from 0');
  });

  it('shows a distance only when it has a location to measure from', () => {
    expect(shopCard(provider(), { lat: 28.62, lng: 77.21 })).toContain('km away');
    expect(shopCard(provider())).not.toContain('km away');
  });

  it('lazy-loads a photo so the page does not fetch every shop at once', () => {
    const html = shopCard(provider({ photo: 'https://cdn.example/a.jpg' }));

    expect(html).toContain('loading="lazy"');
  });

  it('falls back to an initial when there is no photo', () => {
    const html = shopCard(provider({ display_name: 'Sharp Cuts Studio' }));

    expect(html).toContain('shop-avatar-fallback');
    expect(html).toContain('S');
  });

  it('marks a decorative initial as hidden from screen readers', () => {
    // The shop name is already next to it; announcing "S" twice is noise.
    expect(shopCard(provider())).toContain('aria-hidden="true"');
  });
});