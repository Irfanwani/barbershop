# Marketing site

The public site and the product knowledge base. Vite + React + TypeScript.

```bash
npm ci
npm run dev        # http://localhost:5173
npm test
npm run build      # typechecks, then builds to dist/
npm run preview    # serves dist/ on :4173
```

The dev server proxies nothing. In development the site talks to
`http://localhost:8000/api/v1` and to `/api/v1` everywhere else; see
`API_BASE` in `src/lib/api.ts`. Override it at runtime with
`window.BARBERSHOP_API_URL` if you need to point at something else.

## Deploying

`npm run build` writes `dist/`. `base` is `./`, so `dist/` can be served from
a domain root, a subpath, or a CDN without rebuilding.

**The server must fall back to `index.html` for unknown paths.** The site is a
single-page app with real routes, so `/knowledge` is not a file — it is the
same `index.html` served for every path. `vite preview` does this for you; a
production host does not, unless you tell it to.

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

45 tests over Vitest and Testing Library. They check the things that actually
break a site: that the page renders when the API is down, that a missing price
renders `—` and not `₹0.00`, that a thin price sample is not labelled
"typical", and that the knowledge base has no duplicate anchors.

The knowledge base content is data (`src/content/knowledge.ts`), and its
structure is asserted rather than assumed — every entry needs an id for
anchors to link, and any answer describing something unshipped has to say so.

## Adding to the knowledge base

Add an entry to `src/content/knowledge.ts`. Give it an `id` (it becomes the
anchor), a question phrased the way someone would ask it, and an answer that
says what happens rather than what the feature is called. `keywords` exist so
searching "money back" finds "How do refunds work?".

Coverage thresholds are set in `vitest.config.ts`.