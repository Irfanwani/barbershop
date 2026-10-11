import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchPrices, fetchShops } from '@/lib/api';
import type { Origin, PriceBand, Provider } from '@/lib/types';

/**
 * Data loading for the marketing page.
 *
 * Written by hand rather than pulled from a query library. The site has two
 * endpoints and a "load more" button; a cache with invalidation, retries and
 * stale-while-revalidate would be more code than the page.
 *
 * The rule every branch here obeys: a failed API never blanks the page. A
 * marketing page that replaces itself with an error box when the backend
 * hiccups is worse than one showing fewer numbers, because the visitor who
 * arrived is the only one who can be recruited right now.
 */

export interface Async<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

const IDLE: Async<never> = { data: null, error: null, loading: false };

export function usePrices(): Async<PriceBand[]> {
  const [state, setState] = useState<Async<PriceBand[]>>(IDLE);

  useEffect(() => {
    let live = true;
    setState({ data: null, error: null, loading: true });
    fetchPrices()
      .then((bands) => live && setState({ data: bands, error: null, loading: false }))
      .catch(() => live && setState({ data: null, error: 'Prices are not loading', loading: false }));
    return () => {
      live = false;
    };
  }, []);

  return state;
}

export interface ShopsResult extends Async<Provider[]> {
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => void;
}

export function useShops(): ShopsResult {
  const [state, setState] = useState<Async<Provider[]>>({ data: null, error: null, loading: true });
  // The caller owns the origin so it can show it on the card as well as sort by it.
  const [origin] = useState<Origin | null>(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  // A generation counter rather than an abort flag: a response that arrives
  // after the user has moved on must not be appended to the current list.
  useEffect(() => {
    let live = true;
    setState({ data: null, error: null, loading: true });
    fetchShops(1, origin)
      .then((body) => {
        if (!live) return;
        setState({ data: body.results ?? [], error: null, loading: false });
        setHasMore(Boolean(body.next));
      })
      .catch(() => {
        if (!live) return;
        setState({ data: null, error: 'Shops are not loading', loading: false });
        setHasMore(false);
      });
    return () => {
      live = false;
    };
  }, [origin]);

  const loadMore = useCallback(() => {
    setLoadingMore(true);
    const next = page + 1;
    fetchShops(next, origin)
      .then((body) => {
        setState((current) => ({
          data: [...(current.data ?? []), ...(body.results ?? [])],
          error: null,
          loading: false,
        }));
        setPage(next);
        setHasMore(Boolean(body.next));
      })
      .catch(() => setLoadingMore(false))
      .finally(() => setLoadingMore(false));
  }, [origin, page]);

  return { ...state, hasMore, loadingMore, loadMore };
}

/**
 * Ask the browser where we are.
 *
 * The capability is checked as a function, not as a property: browsers define
 * `navigator.geolocation` even where it cannot be used, so `'geolocation' in
 * navigator` is true on a device that will refuse every request.
 */
export function useGeolocation(onLocated: (origin: Origin) => void): {
  supported: boolean;
  status: string;
  locate: () => void;
} {
  const supported =
    typeof navigator !== 'undefined' &&
    typeof navigator.geolocation?.getCurrentPosition === 'function';

  const [status, setStatus] = useState(
    supported ? '' : 'This browser cannot share your location.',
  );

  // Kept in a ref so `locate` stays referentially stable: the callback is
  // usually an inline arrow from the page component, and a fresh identity on
  // every render would be a dependency someone eventually gets wrong.
  const handler = useRef(onLocated);
  useEffect(() => {
    handler.current = onLocated;
  }, [onLocated]);

  const locate = useCallback(() => {
    if (!supported) return;
    setStatus('Asking your browser…');
    navigator.geolocation.getCurrentPosition(
      (position) => {
        // Rounded before it is sent: the extra digits are more precision than
        // a radius search over city-sized data can justify.
        setStatus('Sorted by distance.');
        handler.current({
          lat: Number(position.coords.latitude.toFixed(5)),
          lng: Number(position.coords.longitude.toFixed(5)),
        });
      },
      // A refusal is a choice, not a failure to apologise for.
      () => setStatus('No problem — showing every shop instead.'),
      { timeout: 8000 },
    );
  }, [supported]);

  return { supported, status, locate };
}
