/**
 * Pure helpers for the marketing site.
 *
 * Separated from `app.js` so they can be tested without a DOM. Everything here
 * is a function of its arguments: no fetch, no `window`, no side effects.
 */

/** Text that is safe to put in innerHTML. */
export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

/**
 * Paise to a rupee string.
 *
 * Returns an em dash rather than "₹NaN" or "₹0.00" for anything that is not a
 * finite number, because a missing price displayed as ₹0.00 is a lie a
 * customer acts on.
 */
export function formatPaise(minor) {
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
export function describeBand(band) {
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
    note: `Most fall between ${band.p25_display} and ${band.p75_display} · from ${
      band.sample_size
    } shops`,
    thin: false,
  };
}

/**
 * Build a query string, dropping anything empty.
 *
 * Sends `?lat=&lng=` otherwise, which a server may read as a real zero and
 * happily sort every shop by distance from Null Island.
 */
export function buildQuery(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === '') continue;
    search.set(key, String(value));
  }
  return search.toString();
}

const EARTH_RADIUS_METRES = 6371000;

/** Great-circle distance, for showing "1.2 km away" before the server sorts. */
export function haversineMetres(a, b) {
  if (!a || !b) return null;
  const toRad = (deg) => (deg * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.sin(dLng / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return Math.round(EARTH_RADIUS_METRES * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h)));
}

/** Render a shop card. Pure string in, string out. */
export function shopCard(provider, origin = null) {
  const initial = (provider.display_name || '?').trim().charAt(0).toUpperCase();
  const avatar = provider.photo
    ? `<img class="shop-avatar" src="${escapeHtml(provider.photo)}" alt="" loading="lazy" />`
    : `<div class="shop-avatar shop-avatar-fallback" aria-hidden="true">${escapeHtml(
        initial,
      )}</div>`;

  const metres = origin ? haversineMetres(origin, provider.approximate_location) : null;
  const meta = [
    provider.service_type_label,
    provider.is_open_now ? 'Open now' : 'Closed now',
    provider.rating_count
      ? `${provider.rating_average} from ${provider.rating_count}`
      : 'No reviews yet',
    metres !== null ? `${(metres / 1000).toFixed(1)} km away` : null,
  ]
    .filter(Boolean)
    .join(' · ');

  // A closed shop still shows its price, greyed rather than hidden. "Why is
  // this one cheaper" is a fair question and hiding it invites a refresh that
  // will not change the answer.
  const from = provider.is_accepting_bookings
    ? `<p class="shop-from"><span>From</span><strong>${escapeHtml(
        provider.starting_price_display ?? '—',
      )}</strong></p>`
    : '<p class="shop-from"><span class="shop-closed">Not taking bookings</span></p>';

  return `
    <article class="shop-card">
      ${avatar}
      <div>
        <h3 class="shop-name">${escapeHtml(provider.display_name)}</h3>
        <p class="shop-meta">${escapeHtml(meta)}</p>
      </div>
      ${from}
    </article>`;
}

/** Render the price grid. Returns an HTML string. */
export function renderPrices(bands) {
  const usable = (bands ?? []).filter((band) => describeBand(band));

  if (usable.length === 0) {
    return '<p class="muted">Not enough prices listed yet. Once a few shops list what they charge, the usual range appears here.</p>';
  }

  return usable
    .map((band) => {
      const copy = describeBand(band);
      // The label follows the sample size. A card reading "Typical ₹300" over a
      // note saying "based on 1 shop" is a confident lie with a footnote.
      const medianLabel = copy.thin ? 'Median' : 'Typical';
      return `
        <article class="price-card">
          <h3>${escapeHtml(band.service_type_label)}</h3>
          <p class="price-headline">${escapeHtml(copy.headline)}</p>
          <div class="price-figures">
            <p class="price-figure">
              <span>${medianLabel}</span>
              <strong>${escapeHtml(band.median_display ?? '—')}</strong>
            </p>
            <p class="price-figure">
              <span>Lowest</span>
              <strong>${escapeHtml(band.minimum_display ?? '—')}</strong>
            </p>
            <p class="price-figure">
              <span>Highest</span>
              <strong>${escapeHtml(band.maximum_display ?? '—')}</strong>
            </p>
          </div>
          <p class="price-note${copy.thin ? ' is-thin' : ''}">${escapeHtml(copy.note)}</p>
        </article>`;
    })
    .join('');
}