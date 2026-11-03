# Marketing site

The public site for BarberShop: a landing page explaining what the app does and
where to download it, plus the product knowledge base. Vite + React +
TypeScript.

The site is intentionally static. It is a front door, not a second client — all
booking, payment and shop-management features live in the mobile app. That
means the site has no API dependency and cannot show a blank page when the
backend is unreachable.

```bash
npm ci
npm run dev        # http://localhost:5173
npm run typecheck  # tsc --noEmit
npm run lint       # eslint
npm test
npm run build      # typechecks, then builds to dist/
npm run preview    # serves dist/ on :4173
```

`npm run build` already runs `tsc --noEmit` first, so a type error fails the
build rather than shipping.

## Download links

The App Store and Google Play URLs live in `STORE_LINKS` in
`src/content/site.ts`. The Android link uses the package name from
`apps/mobile/app.json`; the App Store link is a store search until the listing
has a numeric app id. Update both in one place when the listings go live.

## Deploying

The live site is published at **https://irfanwani.github.io/barbershop** by
[`.github/workflows/deploy-web.yml`](../../.github/workflows/deploy-web.yml).
It runs on every push to `main` that touches `apps/web/**` (and can be started
by hand with `workflow_dispatch`). The paths filter is deliberate: GitHub
already compares the tree, so there is no version number to remember to bump —
only an actual website change starts a deploy.

The workflow typechecks, lints, tests and builds with
`VITE_BASE_PATH=/barbershop/`, copies `dist/index.html` to `dist/404.html` for
GitHub Pages (which has no SPA fallback), and uploads the result with the Pages
actions.

For any other host, `npm run build` writes `dist/`. `base` is `./` by default,
so the output can be served from a domain root or a CDN. For a subpath, set
`VITE_BASE_PATH` to that prefix (with a trailing slash) at build time so the
router and assets agree.

**The server must fall back to `index.html` for unknown paths.** The site is a
single-page app with real routes, so `/knowledge` is not a file — it is the
same `index.html` served for every path. `vite preview` does this for you; a
production host does not, unless you tell it to. GitHub Pages uses the
`404.html` copy made by the workflow.

```nginx
location / {
  try_files $uri $uri/ /index.html;
}
```

```apache
FallbackResource /index.html
```

For S3 or any static host, set the error document to `index.html` and keep the
error status a 200.

Without that rule every deep link and every refresh of `/knowledge` is a 404.
The CI job checks the built output over HTTP precisely because nothing else
catches it.

## Testing

33 tests over Vitest and Testing Library. They check the things that actually
break a marketing site: that the page names the product and its audience, that
every store and knowledge-base link goes somewhere that exists, and that the
footer does not reintroduce links to files that are not part of the deploy.
One test covers the scroll-reveal observer directly; the rest of the suite
renders with the no-IntersectionObserver fallback that real old browsers get.

The knowledge base content is data (`src/content/knowledge.ts`), and its
structure is asserted rather than assumed — every entry needs an id for
anchors to link, and any answer describing something unshipped has to say so.

## Adding to the knowledge base

Add an entry to `src/content/knowledge.ts`. Give it an `id` (it becomes the
anchor), a question phrased the way someone would ask it, and an answer that
says what happens rather than what the feature is called. `keywords` exist so
searching "money back" finds "How do refunds work?".

Coverage thresholds are set in `vitest.config.ts`.

CI additionally serves the built output and fetches it over HTTP — `/`,
`/knowledge`, both logo assets and an unknown route must answer 200. That
last one is the SPA fallback, and it is the only thing in the pipeline that
would notice a deployment losing it.
