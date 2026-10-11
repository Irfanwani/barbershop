/**
 * Jest setup for the site.
 *
 * Uses the *real* `index.html` as the document rather than a hand-built
 * fake. A stub DOM can drift from the page until the tests pass and the page is
 * broken; the real markup cannot. If the HTML loses an id this app depends on,
 * these tests fail — which is the point.
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import '@testing-library/jest-dom';

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, '..', 'index.html'), 'utf8');

/** The `<body>` of the real page, without the document wrapper. */
const body = html.slice(html.indexOf('<body') + 5, html.lastIndexOf('</body>'));

beforeEach(() => {
  document.body.innerHTML = body;
  document.head.innerHTML = html.slice(
    html.indexOf('<head>') + 6,
    html.lastIndexOf('</head>'),
  );
  document.body.setAttribute('aria-busy', 'false');
});

export function jsonResponse(bodyJson, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => bodyJson };
}

/** Record every URL fetched and reply with `handler(url)`. */
export function installFetch(handler) {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    return handler(String(url));
  };
  return calls;
}

export function band(overrides = {}) {
  return {
    service_type: 'barbershop',
    service_type_label: 'Barber shop',
    sample_size: 12,
    minimum: 20000,
    minimum_display: '₹200.00',
    maximum: 40000,
    maximum_display: '₹400.00',
    median: 30000,
    median_display: '₹300.00',
    p25: 25000,
    p25_display: '₹250.00',
    p75: 35000,
    p75_display: '₹350.00',
    is_thin: false,
    ...overrides,
  };
}

export function provider(overrides = {}) {
  return {
    id: 1,
    display_name: 'Sharp Cuts Studio',
    service_type_label: 'Barber shop',
    photo: null,
    is_open_now: true,
    is_accepting_bookings: true,
    rating_average: '4.80',
    rating_count: 126,
    starting_price_display: '₹250.00',
    approximate_location: { lat: 28.6139, lng: 77.209 },
    ...overrides,
  };
}