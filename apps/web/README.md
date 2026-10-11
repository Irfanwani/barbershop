# The marketing site

Static HTML, CSS and JavaScript. No framework, no build step, no bundler.

That is a deliberate constraint rather than an accident of a small page. The
site deploys to anything that serves files, cannot rot because a dependency had
a major release, and the files a browser downloads are the files in this
directory.

## Running it

```bash
npm install          # only needed for the tests
npm start            # serves on :4173
```

Open <http://localhost:4173>. The page reads the live API; start the backend
first (`make dev-api` from the repository root) or the price and shop lists
will say so rather than appearing empty.

To point the page at a backend on another host, set `window.BARBERSHOP_API_URL`
before `app.js` loads. With no override it uses `/api/v1` on the same origin,
except on `localhost`, where it uses `http://localhost:8000/api/v1`.

## Tests

```bash
npm test
npm run test:coverage
```

Jest runs the same ES modules the browser runs. Nothing is transpiled —
`transform: {}` in `jest.config.js` hands the source to Node untouched — so a
file that works in a test works in a browser.

The DOM tests run against the real `index.html` rather than a hand-built fake.
A stub DOM drifts from the page until the tests pass and the page is broken;
the real markup cannot.

## Layout

| File         | What it is                                                    |
| ------------ | ------------------------------------------------------------- |
| `index.html` | The page. Also the fixture the DOM tests run against.          |
| `styles.css` | All of it. Dark mode via `prefers-color-scheme`.               |
| `lib.js`     | Pure functions: formatting, escaping, rendering. No fetch.     |
| `app.js`     | The wiring: fetch, listeners, and the wiring between them.     |

Splitting `lib.js` out is what makes the interesting half testable. Every
number the site shows is formatted or rendered in one place, and none of it
touches the network.

## Deploying

Serve the directory. `dist/` is not needed.

The only requirement is that `/api/v1` either resolves on the same origin or is
set through `window.BARBERSHOP_API_URL` before `app.js` loads. If the API is
unreachable the page still renders — it says the prices and shops are not
loading, rather than showing an empty grid or an error box.
