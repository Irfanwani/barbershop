import { Link } from 'react-router-dom';

import {
  ArrowUpRight,
  CheckIcon,
  DownloadArt,
  FeatureArtwork,
  PinIcon,
  ScissorsMark,
  Sparkle,
  StarIcon,
  StepArtwork,
} from '@/components/Illustrations';
import { Reveal } from '@/components/Reveal';
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

const MARQUEE_ITEMS = [
  'Real availability',
  'No surprise prices',
  'Deposits & balances',
  'Reminders that land',
  'Payouts that clear',
  'One app, two roles',
];

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
      className={`store-button store-button--${link.id}`}
      href={link.href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`${link.eyebrow} ${link.store} — ${link.platform}`}>
      <span className="store-icon">{link.id === 'ios' ? <AppleIcon /> : <PlayIcon />}</span>
      <span className="store-copy">
        <span className="store-eyebrow">{link.eyebrow}</span>
        <strong>{link.store}</strong>
      </span>
      <ArrowUpRight className="store-arrow" />
    </a>
  );
}

function FeatureRow({ feature, index }: { feature: Feature; index: number }) {
  return (
    <li>
      <Reveal className="feature-row" delay={index * 55}>
        <span className="feature-icon">
          <FeatureArtwork art={feature.art} />
        </span>
        <div className="feature-copy">
          <strong>{feature.title}</strong>
          <p>{feature.body}</p>
        </div>
      </Reveal>
    </li>
  );
}

export default function Home() {
  return (
    <>
      <section className="hero">
        <div className="hero-wash hero-wash--one" aria-hidden="true" />
        <div className="hero-wash hero-wash--two" aria-hidden="true" />
        <div className="wrap hero-inner">
          <Reveal className="hero-copy">
            <p className="eyebrow">
              <span className="eyebrow-dot" aria-hidden="true" />
              One app · Both sides of the chair
            </p>
            <h1 className="hero-title">
              Book the chair.{' '}
              <span className="hero-title-accent">
                Run the shop.
                <svg className="hero-underline" viewBox="0 0 340 18" aria-hidden="true">
                  <path
                    className="art-draw d1"
                    pathLength={1}
                    d="M5 12c55-8 106-9 164-6 52 2 104 4 166-2"
                    fill="none"
                    stroke="var(--accent)"
                    strokeWidth="6"
                    strokeLinecap="round"
                  />
                </svg>
              </span>
            </h1>
            <p className="lede">
              BarberShop is the app for people who want a haircut and the people who give one.
              Find a shop, see the price before you confirm, and take a slot from the shop’s
              real calendar — or run your whole business from the same place.
            </p>
            <div className="hero-actions">
              <Link className="button" to="/#download">
                Get the app
                <ArrowUpRight className="button-icon" />
              </Link>
              <Link className="button button-ghost" to="/knowledge">
                Browse the knowledge base
              </Link>
            </div>
            <ul className="hero-proof">
              <li>
                <CheckIcon /> Free for customers
              </li>
              <li>
                <CheckIcon /> Providers pay 1%
              </li>
              <li>
                <CheckIcon /> No surprise prices
              </li>
            </ul>
          </Reveal>

          <Reveal className="hero-visual" delay={140}>
            <div className="hero-stage" aria-hidden="true">
              <div className="hero-glow" />
              <svg className="hero-orbit" viewBox="0 0 460 460" focusable="false">
                <circle
                  cx="230"
                  cy="230"
                  r="186"
                  fill="none"
                  stroke="var(--line-strong)"
                  strokeWidth="1.5"
                  strokeDasharray="4 10"
                />
                <circle cx="230" cy="44" r="5" fill="var(--accent)" />
                <circle cx="386" cy="310" r="4" fill="var(--gold)" />
              </svg>
              <Sparkle className="hero-sparkle hero-sparkle--one" />
              <Sparkle className="hero-sparkle hero-sparkle--two" />

              <div className="app-preview">
                <div className="app-topbar">
                  <span className="app-logo">
                    <img src="./assets/logo-512.png" alt="" width={28} height={28} />
                  </span>
                  <span className="app-name">BarberShop</span>
                  <span className="app-live">
                    <span /> Live
                  </span>
                </div>

                <div className="role-toggle">
                  <span className="is-active">Customer</span>
                  <span>Provider</span>
                </div>

                <div className="preview-shop">
                  <div className="preview-shop-head">
                    <span className="preview-avatar">F</span>
                    <div className="preview-shop-name">
                      <strong>Fade &amp; Co.</strong>
                      <span>
                        <StarIcon /> 4.9 · 0.8 km
                      </span>
                    </div>
                    <span className="preview-open">Open</span>
                  </div>

                  <div className="preview-service">
                    <span>
                      <strong>Skin fade + beard</strong>
                      <small>45 min · today</small>
                    </span>
                    <strong>₹450</strong>
                  </div>

                  <p className="preview-label">Next available</p>
                  <div className="preview-slots">
                    <span className="slot is-selected">6:30</span>
                    <span className="slot">7:15</span>
                    <span className="slot">8:00</span>
                  </div>

                  <div className="preview-cta">Book · ₹100 deposit</div>
                  <p className="preview-note">
                    <CheckIcon /> Full price shown before you confirm
                  </p>
                </div>

                <div className="app-home-bar" />
              </div>

              <div className="float-card float-card--confirm">
                <span className="float-icon float-icon--check">
                  <CheckIcon />
                </span>
                <span>
                  <strong>Confirmed</strong>
                  <small>Sat · 11:30</small>
                </span>
              </div>

              <div className="float-card float-card--price">
                <span>
                  <small>Deposit paid</small>
                  <strong>₹100</strong>
                </span>
                <span className="float-pill">Balance ₹350</span>
              </div>

              <div className="float-sticker">
                Fresh cut
                <br />
                booked
              </div>

              <div className="float-rating">
                <StarIcon />
                <strong>4.9</strong>
                <small>128 reviews</small>
              </div>

              <span className="hero-pin">
                <PinIcon />
              </span>
            </div>
          </Reveal>
        </div>

        <div className="marquee" aria-hidden="true">
          <div className="marquee-track">
            {[0, 1].map((copy) => (
              <div className="marquee-group" key={copy}>
                {MARQUEE_ITEMS.map((item) => (
                  <span className="marquee-item" key={item}>
                    <ScissorsMark />
                    {item}
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="features" className="section features-section">
        <div className="wrap">
          <Reveal className="section-head section-head--split">
            <div>
              <p className="eyebrow">What it does</p>
              <h2 className="section-title">
                Two sides of the chair, <em>one app.</em>
              </h2>
            </div>
            <p className="section-lede">
              Customers book and pay. Providers take the booking, collect the money and see
              their earnings. Both use the same app; your role decides what you see.
            </p>
          </Reveal>

          <div className="feature-grid">
            <Reveal className="feature-card feature-card--customer">
              <span className="feature-card-stamp" aria-hidden="true">
                01 / Customer
              </span>
              <header className="feature-card-head">
                <p className="feature-eyebrow">
                  <span className="feature-role-dot" aria-hidden="true" />
                  For customers
                </p>
                <h3>Find the right shop, then get on with your day.</h3>
                <p className="feature-intro">
                  Browse nearby shops, compare the real price and take a time that actually
                  exists. Everything up to the chair happens in a few taps.
                </p>
              </header>

              <ul className="feature-list">
                {CUSTOMER_FEATURES.map((feature, index) => (
                  <FeatureRow feature={feature} index={index} key={feature.title} />
                ))}
              </ul>

              <Link className="text-link" to="/knowledge#booking">
                Customer guide
                <ArrowUpRight className="text-link-icon" />
              </Link>
            </Reveal>

            <Reveal className="feature-card feature-card--provider" delay={90}>
              <span className="feature-card-stamp" aria-hidden="true">
                02 / Provider
              </span>
              <header className="feature-card-head">
                <p className="feature-eyebrow">
                  <span className="feature-role-dot" aria-hidden="true" />
                  For providers
                </p>
                <h3>Run the shop, not a spreadsheet and three group chats.</h3>
                <p className="feature-intro">
                  Your calendar, your money and your customers in one place — with the records
                  attached to the booking instead of scattered across notes.
                </p>
              </header>

              <ul className="feature-list">
                {PROVIDER_FEATURES.map((feature, index) => (
                  <FeatureRow feature={feature} index={index} key={feature.title} />
                ))}
              </ul>

              <Link className="text-link" to="/knowledge#provider">
                Provider guide
                <ArrowUpRight className="text-link-icon" />
              </Link>
            </Reveal>
          </div>
        </div>
      </section>

      <section id="how" className="section how-section">
        <div className="how-glow how-glow--one" aria-hidden="true" />
        <div className="how-glow how-glow--two" aria-hidden="true" />
        <div className="wrap">
          <Reveal className="section-head section-head--split section-head--light">
            <div>
              <p className="eyebrow eyebrow--lime">How it works</p>
              <h2 className="section-title">How booking works</h2>
            </div>
            <p className="section-lede">
              Three steps, and the awkward parts — finding a free slot and agreeing a price —
              happen before you commit rather than at the counter.
            </p>
          </Reveal>

          <ol className="steps">
            {BOOKING_STEPS.map((step, index) => (
              <li key={step.title}>
                <Reveal className="step" delay={index * 100}>
                  <div className="step-top">
                    <span className="step-number">0{index + 1}</span>
                    <span className="step-rule" aria-hidden="true" />
                  </div>
                  <div className="step-art">
                    <StepArtwork art={step.art} />
                  </div>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                </Reveal>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="download" className="section download-section">
        <div className="wrap">
          <Reveal className="download-panel">
            <div className="download-copy">
              <p className="eyebrow eyebrow--cream">Get the app</p>
              <h2 className="section-title">Your next appointment starts here.</h2>
              <p className="section-lede">
                Booking, payments, reminders and the shop’s back office all live in the app.
                Download it free on the App Store or Google Play.
              </p>
              <div className="store-buttons">
                {STORE_LINKS.map((link) => (
                  <StoreButton key={link.id} link={link} />
                ))}
              </div>
              <p className="fineprint">
                Free to download · One account for booking or running a shop
              </p>
            </div>
            <div className="download-visual" aria-hidden="true">
              <DownloadArt />
            </div>
          </Reveal>
        </div>
      </section>

      <section id="questions" className="section section-alt questions-section">
        <div className="wrap">
          <Reveal className="section-head section-head--split">
            <div>
              <p className="eyebrow">Good questions</p>
              <h2 className="section-title">Answers before you ask.</h2>
            </div>
            <p className="section-lede">
              Deposits, refunds, no-shows, earnings and payouts — the knowledge base covers
              how the product works for customers and for providers.
            </p>
          </Reveal>

          <ul className="question-list">
            {POPULAR_QUESTIONS.map((item, index) => (
              <li key={item.entryId}>
                <Reveal className="question-card" delay={index * 70}>
                  <Link to={`/knowledge#${item.entryId}`}>
                    <span className="question-index">0{index + 1}</span>
                    <span className="question-body">
                      <span className="question-tag">{item.tag}</span>
                      <strong>{item.question}</strong>
                    </span>
                    <span className="question-arrow">
                      <ArrowUpRight />
                    </span>
                  </Link>
                </Reveal>
              </li>
            ))}
          </ul>

          <Reveal className="questions-cta" delay={120}>
            <p>Can’t find the answer here? The whole product is documented in the app guide.</p>
            <Link className="button button-ghost" to="/knowledge">
              Open the knowledge base
              <ArrowUpRight className="button-icon" />
            </Link>
          </Reveal>
        </div>
      </section>
    </>
  );
}
