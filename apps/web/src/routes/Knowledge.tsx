import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import {
  ArrowUpRight,
  GroupArtwork,
  KnowledgeHeroArt,
  ScissorsMark,
  Sparkle,
} from '@/components/Illustrations';
import { Reveal } from '@/components/Reveal';
import { groupsFor, searchEntries } from '@/content/knowledge';

/**
 * The knowledge base.
 *
 * Two things this page does that a plain FAQ page would not:
 *
 * 1. It is searchable, because the failure mode of documentation is not that
 *    it is absent, it is that a visitor cannot find the one paragraph they
 *    need. Searches the words people actually type ("money back", "no show")
 *    rather than only the words the question is phrased in.
 *
 * 2. It filters by audience. Customers and providers read this product in
 *    opposite directions, and making one page do both means the half that does
 *    not apply to you is in the way.
 */
export default function Knowledge() {
  const [query, setQuery] = useState('');
  const [audience, setAudience] = useState<'all' | 'customers' | 'providers'>('all');

  const groups = useMemo(() => groupsFor(audience), [audience]);

  const results = useMemo(() => (query.trim() ? searchEntries(query) : null), [query]);

  return (
    <>
      <section className="kb-hero">
        <div className="kb-hero-wash" aria-hidden="true" />
        <div className="wrap kb-hero-inner">
          <Reveal className="kb-hero-copy">
            <p className="eyebrow">
              <span className="eyebrow-dot" aria-hidden="true" />
              Help centre
            </p>
            <h1>Knowledge base</h1>
            <p className="lede">
              How BarberShop works — deposits, cancellations, refunds, earnings and payouts —
              for customers and for providers. Everything here describes the product as it
              works today.
            </p>

            <div className="kb-controls">
              <div className="kb-search">
                <label className="visually-hidden" htmlFor="kb-search">
                  Search the knowledge base
                </label>
                <span className="kb-search-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" focusable="false">
                    <circle
                      cx="10.5"
                      cy="10.5"
                      r="6.5"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    />
                    <path
                      d="m15.5 15.5 5 5"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                    />
                  </svg>
                </span>
                <input
                  id="kb-search"
                  type="search"
                  placeholder="Search refunds or deposits"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  autoComplete="off"
                />
              </div>

              <div className="kb-filters" role="group" aria-label="Who is this for">
                {(
                  [
                    ['all', 'Everyone'],
                    ['customers', 'For customers'],
                    ['providers', 'For providers'],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    className={audience === value ? 'kb-filter is-active' : 'kb-filter'}
                    aria-pressed={audience === value}
                    onClick={() => setAudience(value)}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <p className="kb-hint">
              <Sparkle />
              Search the words you would use. “Money back” finds refunds.
            </p>
          </Reveal>

          <Reveal className="kb-hero-art-wrap" delay={160}>
            <KnowledgeHeroArt />
          </Reveal>
        </div>
      </section>

      <div className={results ? 'wrap kb-layout kb-layout--search' : 'wrap kb-layout'}>
        {!results ? (
          <nav className="kb-toc" aria-label="Contents">
            <p className="kb-toc-title">On this page</p>
            <ul>
              {groups.map((group) => (
                <li key={group.id}>
                  <a href={`#${group.id}`}>
                    <span className="kb-toc-dot" aria-hidden="true" />
                    {group.title}
                  </a>
                  <ul>
                    {group.sections.map((section) => (
                      <li key={section.id}>
                        <a href={`#${section.id}`}>{section.title}</a>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </nav>
        ) : null}

        <div className="kb-body">
          {results ? (
            <section className="kb-results" aria-label="Search results">
              <div className="kb-results-head">
                <h2>
                  {results.length} {results.length === 1 ? 'answer' : 'answers'} for “{query.trim()}”
                </h2>
                <button className="kb-clear" type="button" onClick={() => setQuery('')}>
                  Clear search
                </button>
              </div>

              {results.length === 0 ? (
                <div className="kb-empty">
                  <ScissorsMark />
                  <p>
                    Nothing matched. Try a shorter word — the search looks for it anywhere in
                    the question and the answer.
                  </p>
                </div>
              ) : (
                <div className="kb-result-list">
                  {results.map(({ group, entry }, index) => (
                    <Reveal className="kb-entry" key={entry.id} delay={index * 35}>
                      <span className="kb-entry-tag">{group.title}</span>
                      <h3>{entry.question}</h3>
                      <p>{entry.answer}</p>
                    </Reveal>
                  ))}
                </div>
              )}
            </section>
          ) : (
            groups.map((group) => (
              <section className="kb-group" id={group.id} key={group.id}>
                <Reveal className="kb-group-head">
                  <span className="kb-group-icon">
                    <GroupArtwork id={group.id} />
                  </span>
                  <div>
                    <h2>{group.title}</h2>
                    <p>{group.summary}</p>
                  </div>
                </Reveal>

                {group.sections.map((section) => (
                  <section className="kb-section" id={section.id} key={section.id}>
                    <Reveal className="kb-section-head">
                      <h3>{section.title}</h3>
                      <p>{section.blurb}</p>
                    </Reveal>

                    <dl className="kb-list">
                      {section.entries.map((entry, index) => (
                        <Reveal
                          className="kb-item"
                          id={entry.id}
                          key={entry.id}
                          delay={(index % 4) * 45}>
                          <dt>
                            <span>{entry.question}</span>
                            <a
                              className="kb-anchor"
                              href={`#${entry.id}`}
                              aria-label={`Link to ${entry.question}`}>
                              #
                            </a>
                          </dt>
                          <dd>{entry.answer}</dd>
                        </Reveal>
                      ))}
                    </dl>
                  </section>
                ))}
              </section>
            ))
          )}
        </div>
      </div>

      <section className="section kb-support-section">
        <div className="wrap">
          <Reveal className="kb-support">
            <span className="kb-support-icon" aria-hidden="true">
              <ScissorsMark />
            </span>
            <div>
              <p className="eyebrow">Still stuck?</p>
              <h2 className="section-title">The shop is the shortest route.</h2>
              <p className="section-lede">
                Support is the shop you booked with — they can see your booking, its payments
                and any refund in progress. We do not hold money on your behalf, so they are
                the only people who can move it.
              </p>
            </div>
            <Sparkle className="kb-support-sparkle" />
          </Reveal>
        </div>
      </section>

      <section className="section download-section">
        <div className="wrap">
          <Reveal className="download-panel download-panel--compact">
            <div className="download-copy">
              <p className="eyebrow eyebrow--cream">Ready when you are</p>
              <h2 className="section-title">The app does the booking.</h2>
              <p className="section-lede">
                The knowledge base explains how things work. The app is where you book, pay
                and manage the shop.
              </p>
            </div>
            <Link className="button button-light" to="/#download">
              Get the app
              <ArrowUpRight className="button-icon" />
            </Link>
          </Reveal>
        </div>
      </section>
    </>
  );
}
