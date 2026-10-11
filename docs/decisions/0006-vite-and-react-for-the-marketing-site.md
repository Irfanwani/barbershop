# 0006 — Vite and React for the marketing site

Date: 2026-10-11. Supersedes nothing directly; reverses a choice made in the
first week that was recorded in `apps/web/README.md` rather than here.

## Context

The site was built with no build step: static HTML, one stylesheet, native ES
modules, and a test runner as its only dependency. That was deliberate. The
reasons were real — one fewer toolchain, one fewer thing to break in CI, a
site that cannot fail to build, and a `dist` that is the source.

It was also the right size for the site. At the time it was one page with two
data-dependent sections and three static blocks. In that shape, hand-writing
`innerHTML` costs about the same as writing JSX and debugging a bundle is a
category of problem that does not arise.

## Decision

Move to Vite, React and TypeScript, with Vitest for tests and React Router for
routes.

## Why

**The knowledge base needs a router.** It has five chapters, per-section
anchors, an audience filter and a search box. Deep links like
`/knowledge#getting-paid` have to work, which means history handling, which
means either a router or a hand-rolled implementation of one. Hand-rolling it
to preserve a property that only exists because the site was small is spending
effort on the wrong problem.

**The content outgrew markup.** The knowledge base is ~40 question/answer
pairs. As hand-written HTML that is a thousand lines of `<details>`, and every
edit means touching markup and class names by hand. As data it is edited by
one person in one file and rendered by a component.

**Degrading is a concern that React is good at.** Every rule the old
`app.js` enforced imperatively — a failed API must never blank the page, a
missing price renders `—` and not `₹0.00`, a closed shop still shows its price
— becomes a property of the render tree rather than of an ordering of `catch`
blocks. That is the real reason to prefer it here.

**The no-build argument had an expiry date.** It was never going to survive a
second page. Better to pay the cost knowingly than keep defending a property
that is already false.

## What this costs, honestly

- `npm ci && npm run build` is now a prerequisite for deploying, and a build
  that fails fails the deploy. That is a real loss of a real property.
- Anyone editing the site now needs Node installed. Before, they needed a text
  editor and a browser.
- The CI job goes from "run tests" to "install, typecheck, test, build,
  serve".
- A source map ships unless it is stripped. `sourcemap: true` is set here for
  debugging; a production deploy should turn it off, which is now a decision
  someone has to remember to make.

## Consequences

- The deploy target must serve `index.html` for unknown paths, or `/knowledge`
  is a 404 on refresh. `vite preview` does this in development; nginx,
  GitHub Pages and S3 each need a rewrite rule written down. See
  `apps/web/README.md`.
- 294 kB of JavaScript, 93 kB gzipped, for a marketing page. That is a real
  cost on a slow connection and is the strongest argument for the setup that
  was replaced.
- `escapeHtml` is gone, because React escapes by default. Removing it deleted
  a whole class of bug rather than adding a defence against it.
