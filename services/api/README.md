# BarberShop API

The backend for the BarberShop marketplace: REST API, geospatial provider
search, bookings, payments and reviews.

Part of the [BarberShop monorepo](../../README.md).

## Stack

| Concern       | Choice                          |
| ------------- | ------------------------------- |
| Framework     | Django 5.2, Python 3.13         |
| API           | Django REST Framework 3.16      |
| Auth          | django-rest-knox (opaque tokens) |
| Schema        | drf-spectacular (OpenAPI 3)     |
| Database      | PostgreSQL 16 + PostGIS         |
| Media         | django-storages (S3) or local   |
| Payments      | Razorpay                        |
| Messaging     | Twilio / MSG91 / GXT (WhatsApp) |
| Background    | Celery + Redis                  |
| Dependencies  | uv (`uv.lock` is committed)     |
| Tests         | pytest + pytest-django          |
| Lint / format | ruff                            |
| Types         | mypy + django-stubs             |
| Serving       | Gunicorn behind WhiteNoise      |

Python is pinned to **3.13** in `.python-version`, which is committed. It used to
be gitignored, which meant the file existed on developer machines and not in CI,
so the suite ran on 3.13 locally and 3.12 in CI. CI now asserts the running
interpreter against that file.

## Prerequisites

PostgreSQL with PostGIS, **and the GEOS/GDAL C libraries**.

```bash
# macOS
brew install postgresql@16 postgis geos gdal

# Debian / Ubuntu
sudo apt-get install postgresql-16 postgresql-16-postgis-3 \
                    libgeos-dev libgdal-dev libproj-dev
```

The libraries are not optional and the failure is cryptic if they are missing.
Django's PostGIS backend loads GEOS and GDAL through `ctypes` at import time, so
a missing library does not produce "install PostGIS" — it produces a traceback
through `django/contrib/gis/gdal/libgdal.py` ending in:

```
ImproperlyConfigured: Could not find the GDAL library (tried "gdal", "GDAL", ...)
```

The `-dev` packages are what matter: they provide the unversioned `libgdal.so`
and `libgeos_c.so` symlinks that Django looks up by name. The runtime packages
alone ship only `libgdal.so.32`, which is not on Django's list.

To point at a specific build instead, set `GDAL_LIBRARY_PATH` and
`GEOS_LIBRARY_PATH` to the full path of each `.so`. Both settings accept empty,
which means "look it up yourself".

## Running it

```bash
cp .env.example .env          # then fill in SECRET_KEY and FIELD_ENCRYPTION_KEY
uv sync --all-groups
createdb barbershop
psql barbershop -c 'CREATE EXTENSION IF NOT EXISTS postgis;'
uv run python manage.py migrate
uv run python manage.py runserver
```

| URL                                    | What                      |
| -------------------------------------- | ------------------------- |
| <http://127.0.0.1:8000/api/v1/>        | API root                  |
| <http://127.0.0.1:8000/api/v1/docs/>   | OpenAPI browser           |
| <http://127.0.0.1:8000/admin/>         | Django admin              |
| <http://127.0.0.1:8000/healthz>        | Health check              |

Useful commands:

```bash
uv run python manage.py seed_demo              # realistic demo data to click around in
uv run python manage.py dump_schema            # regenerate docs/openapi.yml
uv run python manage.py spectacular --validate # schema sanity, with warnings
```

## Docker

`services/api/docker-compose.yml` defines six services:

| Service  | What                                                     |
| -------- | -------------------------------------------------------- |
| `db`     | PostgreSQL 16 + PostGIS                                   |
| `redis`  | Broker for Celery                                         |
| `api`    | The API in a container                                    |
| `worker` | Celery worker                                             |
| `beat`   | Celery beat — schedules the background jobs               |
| `test`   | One-shot container for pytest                             |

```bash
docker compose up -d db redis          # just the infrastructure
docker compose up --build api          # the API in a container
docker compose run --rm test           # pytest inside the container
```

## Background jobs

Reminders, waitlist expiry, recurring-occurrence materialisation, exports,
re-booking nudges, risk sweeps and the delivery-health check all run on Celery
beat. None of them work if only the API process is running — the reminder job
that never fires is exactly the silent failure the delivery-health alert exists
to catch.

```bash
uv run celery -A config worker -l info     # worker
uv run celery -A config beat   -l info     # scheduler
```

`config/settings/test.py` sets `CELERY_TASK_ALWAYS_EAGER`, so tasks run inline in
the test suite and nothing needs a broker to run pytest.

## Layout

```
config/            settings package, URLconf, Celery app, WSGI/ASGI entrypoints
core/              shared models, permissions, pagination, errors, money
accounts/          User, roles, email verification, tokens, password reset
providers/         provider profiles, services, hours, availability, analytics, payouts
bookings/          appointments, line items, deposits, recurring series, waitlist, reschedule
reviews/           ratings, comments, photos, reminders, summaries
payments/          orders, capture, webhooks, refunds, ledger, idempotency
promotions/        promo codes, loyalty points, referrals
catalog/           retail products and orders
messaging/         WhatsApp gateway, outbound queue, webhooks
api_keys/          third-party keys, scopes, throttling
risk/              no-show and abuse scoring
exports/           queued CSV exports
observability/     request ids, JSON logs, metrics, alerts
tests/             the pytest suite
```

## Checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy .
uv run pytest                    # add --reuse-db to keep the test database around
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check --deploy
```

All of these run in CI on every push. CI also installs the GEOS/GDAL packages
described above, and asserts the Python version before anything else.

## Settings

`DJANGO_SETTINGS_MODULE` selects one of:

| Module                 | Used for                        |
| ---------------------- | ------------------------------- |
| `config.settings.dev`  | local development (default)     |
| `config.settings.test` | the pytest suite                |
| `config.settings.prod` | production — refuses to boot unconfigured |

Values are read through `config/env.py`, which coerces types and fails loudly on
a missing required variable rather than letting `None` reach the database.
`config.settings.prod` requires `SECRET_KEY`, `ALLOWED_HOSTS`, the five
`POSTGRES_*` values, four `EMAIL_*`/`DEFAULT_FROM_EMAIL`, the three
`RAZORPAY_*` values and `FIELD_ENCRYPTION_KEY`; it raises on boot if any are
missing rather than failing later in production.

`.env.example` documents every variable that settings read. The ones worth
knowing about before you start:

| Variable                              | Needed for                                        |
| ------------------------------------- | ------------------------------------------------- |
| `FIELD_ENCRYPTION_KEY`                | encrypted columns; **the database is unreadable without it** |
| `API_KEY_SALT`                        | hashing third-party API keys                      |
| `WHATSAPP_*` (six variables)          | any WhatsApp send — unset means a silent no-op    |
| `PUSH_NOTIFICATION_URL`               | push delivery; unset means reminders never arrive |
| `SENTRY_DSN`, `LOG_FORMAT`            | observability; without a DSN, errors are logged with their request id instead |
| `GDAL_LIBRARY_PATH`, `GEOS_LIBRARY_PATH` | only if the libraries are somewhere unusual     |

Optional integrations behave quietly when unset rather than raising: no
`RAZORPAY_KEY_ID` means payment endpoints refuse to create orders, no
`WHATSAPP_PROVIDER` means bookings are confirmed by email only, and no
`AI_ENDPOINT` means service suggestions fall back to keyword matching. That is
deliberate — it keeps a development machine runnable — but it does mean an unset
variable looks exactly like a working feature that is doing nothing.

See [`docs/TEST_CASES.md`](../../docs/TEST_CASES.md) for what the suite covers and
which checks still need real credentials.
