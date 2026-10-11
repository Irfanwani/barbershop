/**
 * BarberShop marketing site.
 *
 * Reads the live API, with no build step. Everything degrades: if the API is
 * down, the page still renders and says so, because a marketing page that shows
 * an error box when the backend hiccups is worse than one showing fewer numbers.
 *
 * Rendering lives in `lib.js` as pure functions; this file is only the wiring.
 */

import { buildQuery, renderPrices, shopCard } from './lib.js';

const API_BASE = (
  (typeof window !== 'undefined' && window.BARBERSHOP_API_URL) ||
  (typeof location !== 'undefined' &&
  (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://localhost:8000/api/v1'
    : '/api/v1')
).replace(/\/$/, '');

export { API_BASE };

export const PAGE_SIZE = 10;

async function apiGet(path, params) {
  const query = buildQuery(params);
  const response = await fetch(`${API_BASE}${path}${query ? `?${query}` : ''}`, {
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`${path} responded ${response.status}`);
  }
  return response.json();
}

function reportError(container, what) {
  // Say what is missing without apologising for it.
  container.innerHTML = `<p class="muted">${what} — this part of the page needs the API to be reachable.</p>`;
  container.setAttribute('aria-busy', 'false');
}

const state = { origin: null, page: 1, loading: false };

export async function loadPrices() {
  const container = document.getElementById('price-loading');
  try {
    const body = await apiGet('/providers/prices/');
    container.innerHTML = renderPrices(body.bands ?? []);
  } catch {
    reportError(container, 'Prices are not loading');
  }
  container.setAttribute('aria-busy', 'false');
}

export async function loadShops(page = 1, { append = false } = {}) {
  const container = document.getElementById('shops-list');
  const more = document.getElementById('shops-more');

  if (state.loading) return;
  state.loading = true;

  try {
    const body = await apiGet('/providers/', {
      page,
      page_size: PAGE_SIZE,
      ...(state.origin ? { lat: state.origin.lat, lng: state.origin.lng } : {}),
    });

    const providers = body.results ?? [];
    if (append) {
      container.insertAdjacentHTML(
        'beforeend',
        providers.map((provider) => shopCard(provider, state.origin)).join('\n'),
      );
    } else {
      container.innerHTML =
        providers.length === 0
          ? '<p class="muted">No shops listed yet. Once providers sign up they appear here.</p>'
          : providers.map((provider) => shopCard(provider, state.origin)).join('\n');
    }

    more?.classList.toggle('is-hidden', !body.next);
    more?.classList.toggle('is-block', Boolean(body.next));
    state.page = page;
  } catch {
    if (!append) reportError(container, 'Shops are not loading');
  } finally {
    state.loading = false;
    container.setAttribute('aria-busy', 'false');
  }
}

export function initLocation() {
  const button = document.getElementById('locate-button');
  const status = document.getElementById('locate-status');

  // Check the capability, not the property: browsers define
  // `navigator.geolocation` even where it cannot be used, so `in` is true on
  // a browser that will refuse every request.
  const canLocate = typeof navigator.geolocation?.getCurrentPosition === 'function';

  if (!button || !canLocate) {
    if (button) button.disabled = true;
    if (status) status.textContent = 'This browser cannot share your location.';
    return;
  }

  button.addEventListener('click', () => {
    status.textContent = 'Asking your browser…';
    navigator.geolocation.getCurrentPosition(
      (position) => {
        // Rounded before it is sent: the extra digits are more precision than
        // a radius search over city-sized data can justify.
        state.origin = {
          lat: Number(position.coords.latitude.toFixed(5)),
          lng: Number(position.coords.longitude.toFixed(5)),
        };
        status.textContent = 'Sorted by distance.';
        void loadShops(1);
      },
      () => {
        // A refusal is a choice, not a failure to apologise for.
        status.textContent = 'No problem — showing every shop instead.';
      },
      { timeout: 8000 },
    );
  });
}

/**
 * Start the page.
 *
 * Exported rather than run on import: a module that fetches the moment it is
 * loaded cannot be imported by a test without the test meaning to start the
 * network. `index.html` calls this explicitly.
 */
export function init() {
  initLocation();

  document
    .getElementById('shops-more')
    ?.addEventListener('click', () => void loadShops(state.page + 1, { append: true }));

  void loadPrices();
  void loadShops(1);
}