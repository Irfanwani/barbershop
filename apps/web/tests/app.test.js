/**
 * The site, wired to a stubbed browser but running against the real
 * `index.html`.
 *
 * These are the questions worth asking of a marketing page: what happens when
 * the API is down, does it ever claim a number it does not have, and does it
 * put anything a provider typed into innerHTML without escaping it.
 */

import { API_BASE, PAGE_SIZE, initLocation, loadPrices, loadShops } from '../app.js';
import { band, installFetch, jsonResponse, provider } from './setup.js';

describe('the page', () => {
  it('has the elements the app writes to', () => {
    // Cheap structural check. If index.html loses one of these, every test
    // below would otherwise fail for the same unhelpable reason.
    expect(document.getElementById('price-loading')).not.toBeNull();
    expect(document.getElementById('shops-list')).not.toBeNull();
    expect(document.getElementById('shops-more')).not.toBeNull();
    expect(document.getElementById('locate-button')).not.toBeNull();
  });

  it('starts each section saying it is loading', () => {
    expect(document.getElementById('price-loading').textContent).toContain('Loading prices');
    expect(document.getElementById('shops-list').textContent).toContain('Loading shops');
  });
});

describe('the API base URL', () => {
  it('never ends in a slash, so paths do not double up', () => {
    expect(API_BASE.endsWith('/')).toBe(false);
  });
});

describe('prices', () => {
  it('renders a card per shop type', async () => {
    installFetch(() => jsonResponse({ bands: [band(), band({ service_type_label: 'Spa' })] }));

    await loadPrices();

    const html = document.getElementById('price-loading').innerHTML;
    expect(html).toContain('Barber shop');
    expect(html).toContain('Spa');
    expect(html).toContain('₹300.00');
  });

  it('stops advertising itself as loading', async () => {
    installFetch(() => jsonResponse({ bands: [] }));

    await loadPrices();

    expect(document.getElementById('price-loading').getAttribute('aria-busy')).toBe('false');
  });

  it('says the page still works when the API is down', async () => {
    installFetch(() => jsonResponse({}, 500));

    await loadPrices();

    const html = document.getElementById('price-loading').innerHTML;
    // The page's job is to be read. A stack trace is not content.
    expect(html).toContain('not loading');
    expect(html).not.toContain('undefined');
  });

  it('says there is not enough data rather than showing an empty grid', async () => {
    installFetch(() => jsonResponse({ bands: [] }));

    await loadPrices();

    expect(document.getElementById('price-loading').innerHTML).toContain('Not enough prices');
  });

  it('does not claim a typical price from a single shop', async () => {
    installFetch(() =>
      jsonResponse({ bands: [band({ is_thin: true, sample_size: 1 })] }),
    );

    await loadPrices();

    const html = document.getElementById('price-loading').innerHTML;
    expect(html).toContain('start around');
    expect(html).not.toContain('Typically');
  });
});

describe('shops', () => {
  it('renders a card per shop', async () => {
    installFetch(() =>
      jsonResponse({
        count: 2,
        next: null,
        results: [provider(), provider({ id: 2, display_name: 'The Clip Joint' })],
      }),
    );

    await loadShops();

    const html = document.getElementById('shops-list').innerHTML;
    expect(html).toContain('Sharp Cuts Studio');
    expect(html).toContain('The Clip Joint');
  });

  it('says so when there are no shops at all', async () => {
    installFetch(() => jsonResponse({ count: 0, next: null, results: [] }));

    await loadShops();

    expect(document.getElementById('shops-list').innerHTML).toContain('No shops listed yet');
  });

  it('hides "show more" when the API has no next page', async () => {
    installFetch(() => jsonResponse({ count: 1, next: null, results: [provider()] }));

    await loadShops();

    expect(document.getElementById('shops-more').classList.contains('is-hidden')).toBe(true);
  });

  it('offers "show more" when there is one', async () => {
    installFetch(() =>
      jsonResponse({ count: 30, next: 'https://x/?page=2', results: [provider()] }),
    );

    await loadShops();

    expect(document.getElementById('shops-more').classList.contains('is-block')).toBe(true);
  });

  it('does not claim a distance it was not given', async () => {
    installFetch(() => jsonResponse({ count: 1, next: null, results: [provider()] }));

    await loadShops();

    // Without a location there is no distance to quote, and inventing one would
    // put every shop in the ocean.
    expect(document.getElementById('shops-list').innerHTML).not.toContain('km away');
  });

  it('escapes a shop name rather than executing it', async () => {
    installFetch(() =>
      jsonResponse({
        count: 1,
        next: null,
        results: [provider({ display_name: '<script>alert(1)</script>' })],
      }),
    );

    await loadShops();

    const html = document.getElementById('shops-list').innerHTML;
    expect(html).not.toContain('<script>alert(1)</script>');
    expect(html).toContain('&lt;script&gt;');
  });

  it('shows a closed shop rather than hiding it', async () => {
    installFetch(() =>
      jsonResponse({
        count: 1,
        next: null,
        results: [provider({ is_accepting_bookings: false, is_open_now: false })],
      }),
    );

    await loadShops();

    // "Why is this one cheaper" is a fair question, and a refresh will not
    // answer it.
    const html = document.getElementById('shops-list').innerHTML;
    expect(html).toContain('Not taking bookings');
    expect(html).toContain('Closed now');
  });

  it('does not show a price for a shop not taking bookings', async () => {
    installFetch(() =>
      jsonResponse({ count: 1, next: null, results: [provider({ is_accepting_bookings: false })] }),
    );

    await loadShops();

    expect(document.getElementById('shops-list').innerHTML).not.toContain('₹250.00');
  });

  it('asks for a page size the API will honour', async () => {
    const calls = installFetch(() => jsonResponse({ count: 0, next: null, results: [] }));

    await loadShops();

    expect(calls[0]).toContain(`page_size=${PAGE_SIZE}`);
  });

  it('does not send a blank location to a server that might read it as zero', async () => {
    const calls = installFetch(() => jsonResponse({ count: 0, next: null, results: [] }));

    await loadShops();

    // `?lat=&lng=` can be read as a real zero, which sorts every shop by
    // distance from Null Island.
    expect(calls[0]).not.toContain('lat=');
    expect(calls[0]).not.toContain('lng=');
  });

  it('degrades to an explanation when the API is down', async () => {
    installFetch(() => jsonResponse({}, 503));

    await loadShops();

    expect(document.getElementById('shops-list').innerHTML).toContain('not loading');
  });
});

describe('location', () => {
  it('disables the button when the browser cannot share a location', () => {
    // A browser that exposes the property but cannot use it. `in` says true
    // here; only calling getCurrentPosition would find out.
    Object.defineProperty(window.navigator, 'geolocation', {
      value: {},
      configurable: true,
    });

    initLocation();

    expect(document.getElementById('locate-button').disabled).toBe(true);
    expect(document.getElementById('locate-status').textContent).toContain('cannot share');
  });

  it('treats a refusal as a choice rather than an error', () => {
    Object.defineProperty(window.navigator, 'geolocation', {
      value: { getCurrentPosition: (_ok, fail) => fail({ code: 1 }) },
      configurable: true,
    });
    installFetch(() => jsonResponse({ count: 0, next: null, results: [] }));

    initLocation();
    document.getElementById('locate-button').click();

    expect(document.getElementById('locate-status').textContent).toContain('No problem');
  });
});