import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';

import { PriceCard, ShopList } from '@/components/Cards';
import { useGeolocation, usePrices, useShops } from '@/hooks/useData';
import type { Origin } from '@/lib/types';

/**
 * The marketing page.
 *
 * Everything degrades: if the API is down the page still renders and says so.
 * A marketing page that replaces itself with an error box when the backend
 * hiccups is worse than one showing fewer numbers, because the visitor who
 * arrived is the only one who can be recruited right now.
 */
export default function Home() {
  const [origin, setOrigin] = useState<Origin | null>(null);
  const { supported, status, locate } = useGeolocation(useCallback((next) => setOrigin(next), []));

  const prices = usePrices();
  const shops = useShops();

  return (
    <>
      <section className="hero">
        <div className="wrap hero-inner">
          <div className="hero-copy">
            <h1>A barber you can actually book.</h1>
            <p className="lede">
              Real availability, the price before you confirm, and honest reviews from people
              who were actually in the chair. No calling round to find out if someone's open.
            </p>
            <div className="hero-actions">
              <a className="button" href="#shops">
                Find a shop near you
              </a>
              <a className="button button-ghost" href="#prices">
                See what things cost
              </a>
            </div>
            <p className="fineprint">Free to use. Providers pay 1% when you book.</p>
          </div>

          <div className="hero-card" aria-hidden="true">
            <div className="phone">
              <div className="phone-notch" />
              <div className="phone-screen">
                <div className="skeleton-row skeleton-title" />
                <div className="skeleton-row" />
                <div className="skeleton-row" />
                <div className="skeleton-row skeleton-short" />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="how" className="section">
        <div className="wrap">
          <h2 className="section-title">How it works</h2>
          <div className="steps">
            <article className="step">
              <span className="step-number">1</span>
              <h3>Find a shop</h3>
              <p>
                Search by distance, filter to the shops open right now, and see the rating from
                people who were actually given a haircut.
              </p>
            </article>
            <article className="step">
              <span className="step-number">2</span>
              <h3>Pick a slot</h3>
              <p>
                The calendar shows what is genuinely free, kept in step with the provider's own
                week. If a shop is shut on Sunday, Sunday is not offered.
              </p>
            </article>
            <article className="step">
              <span className="step-number">3</span>
              <h3>Book it</h3>
              <p>
                You see the full price including the platform fee before you pay, and reminders
                arrive before the appointment so nobody is left waiting.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section id="prices" className="section section-alt">
        <div className="wrap">
          <div className="section-head">
            <h2 className="section-title">Know what things cost</h2>
            <p className="section-lede">
              Every price a provider lists is counted, so you can see the usual range before you
              pick a shop instead of after.
            </p>
          </div>

          <div className="price-grid" aria-busy={prices.loading}>
            {prices.error ? (
              <p className="muted">{prices.error} — this part of the page needs the API to be reachable.</p>
            ) : prices.loading ? (
              <p className="muted">Loading prices…</p>
            ) : (
              (prices.data ?? []).map((band) => <PriceCard key={band.service_type} band={band} />)
            )}
          </div>
        </div>
      </section>

      <section id="shops" className="section">
        <div className="wrap">
          <div className="section-head">
            <h2 className="section-title">Shops near you</h2>
            <p className="section-lede">
              Sorted by how far away they are. Your location is only used in your browser to sort
              this list — it is not stored on our servers.
            </p>
          </div>

          <div className="locate">
            <button type="button" className="button" onClick={locate} disabled={!supported}>
              Use my location
            </button>
            <span className="muted" role="status">
              {status}
            </span>
          </div>

          <div className="shop-list" aria-busy={shops.loading}>
            {shops.error ? (
              <p className="muted">{shops.error} — this part of the page needs the API to be reachable.</p>
            ) : shops.loading ? (
              <p className="muted">Loading shops…</p>
            ) : (
              <ShopList shops={shops.data ?? []} origin={origin} />
            )}
          </div>

          {shops.hasMore ? (
            <button className="button button-ghost" onClick={shops.loadMore} disabled={shops.loadingMore}>
              {shops.loadingMore ? 'Loading…' : 'Show more'}
            </button>
          ) : null}
        </div>
      </section>

      <section id="download" className="section section-alt">
        <div className="wrap download">
          <div>
            <h2 className="section-title">Prefer an app?</h2>
            <p className="section-lede">
              The Android and iOS app does the same thing, plus reminders, saved shops and the
              product shelf.
            </p>
          </div>
          <div className="download-actions">
            <a className="button" href="../mobile">
              Get the app
            </a>
            <Link className="button button-ghost" to="/knowledge">
              Read the knowledge base
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}