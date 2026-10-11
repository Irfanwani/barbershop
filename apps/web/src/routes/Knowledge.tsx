import { useEffect, useMemo, useState } from 'react';

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

  // A deep link like /knowledge#providers has to actually land on the heading.
  // The router does not scroll for you, and a link that positions the viewport
  // nowhere is indistinguishable from a broken link.
  useEffect(() => {
    const { hash } = window.location;
    if (!hash) return;
    const target = document.getElementById(hash.slice(1));
    if (!target) return;
    // After paint, so the element has a box to scroll to.
    requestAnimationFrame(() => target.scrollIntoView());
  }, []);

  return (
    <>
      <section className="kb-hero">
        <div className="wrap">
          <h1>Knowledge base</h1>
          <p className="lede">
            How BarberShop works — deposits, cancellations, refunds, earnings and payouts — for
            customers and for providers. Everything here describes the product as it works today.
          </p>

          <div className="kb-controls">
            <div className="kb-search">
              <label className="visually-hidden" htmlFor="kb-search">
                Search the knowledge base
              </label>
              <input
                id="kb-search"
                type="search"
                placeholder="Try &ldquo;refund&rdquo;, &ldquo;no show&rdquo; or &ldquo;withdraw&rdquo;"
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
        </div>
      </section>

      <div className="wrap kb-layout">
        {!results ? (
          <nav className="kb-toc" aria-label="Contents">
            <p className="kb-toc-title">Contents</p>
            <ul>
              {groups.map((group) => (
                <li key={group.id}>
                  <a href={`#${group.id}`}>{group.title}</a>
                  <ul>
                    {group.sections.map((section) => (
                      <li key={section.id}>
                        <a href={`#${section.id}`} className="muted">
                          {section.title}
                        </a>
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
            <section aria-label="Search results">
              <h2>
                {results.length} {results.length === 1 ? 'answer' : 'answers'} for
                {query.trim() ? ` “${query.trim()}”` : ' everything'}
              </h2>
              {results.length === 0 ? (
                <p className="muted">
                  Nothing matched. Try a shorter word — the search looks for it anywhere in the
                  question and the answer.
                </p>
              ) : (
                results.map(({ group, entry }) => (
                  <article className="kb-entry" key={entry.id}>
                    <h3>{entry.question}</h3>
                    <p>{entry.answer}</p>
                    <p className="kb-entry-meta">
                      <a href={`#${entry.id}`} id={`result-${entry.id}`}>
                        {group.title}
                      </a>
                    </p>
                  </article>
                ))
              )}
            </section>
          ) : (
            groups.map((group) => (
              <section className="kb-group" id={group.id} key={group.id}>
                <h2>{group.title}</h2>
                <p className="section-lede">{group.summary}</p>

                {group.sections.map((section) => (
                  <section className="kb-section" key={section.id}>
                    <h3>{section.title}</h3>
                    <p className="muted">{section.blurb}</p>
                    <dl className="kb-list">
                      {section.entries.map((entry) => (
                        <div className="kb-item" key={entry.id} id={entry.id}>
                          <dt>{entry.question}</dt>
                          <dd>{entry.answer}</dd>
                        </div>
                      ))}
                    </dl>
                  </section>
                ))}
              </section>
            ))
          )}
        </div>
      </div>

      <section className="section section-alt">
        <div className="wrap">
          <h2 className="section-title">Still stuck?</h2>
          <p className="section-lede">
            Support is the shop you booked with — they can see your booking, its payments and any
            refund in progress. We do not hold money on your behalf, so they are the only people
            who can move it.
          </p>
        </div>
      </section>
    </>
  );
}
