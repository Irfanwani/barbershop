import { Link } from 'react-router-dom';

import {
  BOOKING_STEPS,
  CUSTOMER_FEATURES,
  POPULAR_QUESTIONS,
  PROVIDER_FEATURES,
  STORE_LINKS,
  type Feature,
  type StoreLink,
} from '@/content/site';

/**
 * The marketing page.
 *
 * The site is a front door, not a second client: everything that needs data
 * lives in the app, and this page only explains what the app does and where to
 * get it. That keeps a marketing deploy independent of the API — a backend
 * hiccup can never blank the page a visitor arrived on.
 */

function CheckMark() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
      <path
        d="M5 10.5 8.5 14 15 6.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function FeatureList({ features }: { features: Feature[] }) {
  return (
    <ul className="feature-list">
      {features.map((feature) => (
        <li key={feature.title}>
          <span className="feature-check" aria-hidden="true">
            <CheckMark />
          </span>
          <span>
            <strong>{feature.title}.</strong> {feature.body}
          </span>
        </li>
      ))}
    </ul>
  );
}

function AppleIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M16.37 12.72c.02-2.51 2.05-3.71 2.14-3.77-1.17-1.71-2.99-1.95-3.64-1.98-1.55-.16-3.03.91-3.81.91-.79 0-2-.89-3.29-.87-1.69.03-3.25 1-4.12 2.5-1.76 3.06-.45 7.6 1.26 10.08.84 1.21 1.83 2.57 3.14 2.52 1.27-.05 1.74-.82 3.27-.82 1.52 0 1.95.82 3.29.79 1.34-.02 2.21-1.23 3.04-2.47.96-1.39 1.35-2.75 1.37-2.82-.03-.01-2.65-1.02-2.67-4.07ZM13.9 5.16c.69-.84 1.16-2.01 1.03-3.16-1 .04-2.2.67-2.92 1.51-.64.74-1.21 1.92-1.06 3.05 1.12.09 2.26-.57 2.95-1.4Z" />
    </svg>
  );
}

function PlayIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M3.6 1.8 13.8 12 3.6 22.2a1 1 0 0 1-.6-.9V2.7a1 1 0 0 1 .6-.9Zm10.9 10.9 2.3 2.3-10.9 6.3 8.6-8.6Zm3.2-3.2 2.8 1.6a1 1 0 0 1 0 1.8l-2.8 1.6L15.4 12l2.3-2.5ZM5.9 2.7l10.9 6.3-2.3 2.3-8.6-8.6Z" />
    </svg>
  );
}

function StoreButton({ link }: { link: StoreLink }) {
  return (
    <a
      className="store-button"
      href={link.href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`${link.eyebrow} ${link.store} — ${link.platform}`}>
      <span className="store-icon">{link.id === 'ios' ? <AppleIcon /> : <PlayIcon />}</span>
      <span className="store-copy">
        <span className="store-eyebrow">{link.eyebrow}</span>
        <strong>{link.store}</strong>
      </span>
    </a>
  );
}

export default function Home() {
  return (
    <>
      <section className="hero">
        <div className="wrap hero-inner">
          <div className="hero-copy">
            <p className="eyebrow">One app · Both sides of the chair</p>
            <h1>Book the chair. Run the shop.</h1>
            <p className="lede">
              BarberShop is the app for people who want a haircut and the people who give one.
              Find a shop, see the price before you confirm, and take a slot from the shop’s
              real calendar — or run your whole business from the same place.
            </p>
            <div className="hero-actions">
              <Link className="button" to="/#download">
                Get the app
              </Link>
              <Link className="button button-ghost" to="/knowledge">
                Browse the knowledge base
              </Link>
            </div>
            <p className="fineprint">
              Free for customers · Providers pay 1% of completed bookings
            </p>
          </div>

          <div className="hero-card" aria-hidden="true">
            <div className="phone">
              <div className="phone-notch" />
              <div className="phone-screen">
                <div className="phone-bar">
                  <img src="./assets/logo-512.png" alt="" width={24} height={24} />
                  <span>BarberShop</span>
                </div>

                <div className="phone-switch">
                  <span className="is-active">Customer</span>
                  <span>Provider</span>
                </div>

                <p className="phone-label">Next appointment</p>
                <div className="phone-card">
                  <div className="phone-card-top">
                    <strong>Haircut &amp; beard</strong>
                    <span className="phone-chip">Confirmed</span>
                  </div>
                  <p>Saturday · 11:30</p>
                  <p className="phone-card-note">Deposit paid · balance at the chair</p>
                </div>

                <div className="phone-list">
                  <p>
                    <span>Real availability</span>
                    <span className="phone-dot" />
                  </p>
                  <p>
                    <span>Full price before you confirm</span>
                    <span className="phone-dot" />
                  </p>
                  <p>
                    <span>Reminder before the day</span>
                    <span className="phone-dot" />
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="features" className="section">
        <div className="wrap">
          <div className="section-head">
            <h2 className="section-title">Two sides of the chair, one app</h2>
            <p className="section-lede">
              Customers book and pay. Providers take the booking, collect the money and see
              their earnings. Both use the same app; your role decides what you see.
            </p>
          </div>

          <div className="feature-grid">
            <article className="feature-card">
              <p className="feature-eyebrow">For customers</p>
              <h3>Find the right shop, then get on with your day.</h3>
              <FeatureList features={CUSTOMER_FEATURES} />
              <Link className="text-link" to="/knowledge#booking">
                Customer guide →
              </Link>
            </article>

            <article className="feature-card">
              <p className="feature-eyebrow">For providers</p>
              <h3>Run the shop, not a spreadsheet and three group chats.</h3>
              <FeatureList features={PROVIDER_FEATURES} />
              <Link className="text-link" to="/knowledge#provider">
                Provider guide →
              </Link>
            </article>
          </div>
        </div>
      </section>

      <section id="how" className="section section-alt">
        <div className="wrap">
          <div className="section-head">
            <h2 className="section-title">How booking works</h2>
            <p className="section-lede">
              Three steps, and the awkward parts — finding a free slot and agreeing a price —
              happen before you commit rather than at the counter.
            </p>
          </div>

          <ol className="steps">
            {BOOKING_STEPS.map((step, index) => (
              <li className="step" key={step.title}>
                <span className="step-number">{index + 1}</span>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="download" className="section">
        <div className="wrap download-panel">
          <div className="download-copy">
            <p className="eyebrow">Get the app</p>
            <h2 className="section-title">Your next appointment starts here.</h2>
            <p className="section-lede">
              Booking, payments, reminders and the shop’s back office all live in the app.
              Download it free on the App Store or Google Play.
            </p>
          </div>

          <div className="download-actions">
            <div className="store-buttons">
              {STORE_LINKS.map((link) => (
                <StoreButton key={link.id} link={link} />
              ))}
            </div>
            <p className="fineprint">
              Free to download · One account for booking or running a shop
            </p>
          </div>
        </div>
      </section>

      <section id="questions" className="section section-alt">
        <div className="wrap">
          <div className="section-head">
            <h2 className="section-title">Answers before you ask</h2>
            <p className="section-lede">
              Deposits, refunds, no-shows, earnings and payouts — the knowledge base covers
              how the product works for customers and for providers.
            </p>
          </div>

          <ul className="question-list">
            {POPULAR_QUESTIONS.map((item) => (
              <li key={item.entryId}>
                <Link to={`/knowledge#${item.entryId}`}>
                  <span>{item.question}</span>
                  <span aria-hidden="true">→</span>
                </Link>
              </li>
            ))}
          </ul>

          <Link className="button button-ghost" to="/knowledge">
            Open the knowledge base
          </Link>
        </div>
      </section>
    </>
  );
}
