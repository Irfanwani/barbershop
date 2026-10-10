# BarberShop API

The backend for the BarberShop marketplace: REST API, geospatial provider
search, bookings, Razorpay payments and reviews.

Part of the [BarberShop monorepo](../../README.md).

## Stack

| Concern            | Choice                                     |
| ------------------ | ------------------------------------------ |
| Framework          | Django 5.2, Python 3.12                    |
| API                | Django REST Framework 3.16                |
| Auth               | django-rest-knox (opaque tokens)           |
| Schema             | drf-spectacular (OpenAPI 3)               |
| Database           | PostgreSQL 16 + PostGIS                    |
| Media              | django-storages (S3) or local disk         |
| Payments           | Razorpay                                   |
| Dependencies       | uv (`uv.lock` is committed)                |
| Tests              | pytest + pytest-django                     |
| Lint / format      | ruff                                      |
| Types              | mypy + django-stubs                        |
| Serving            | Gunicorn behind WhiteNoise                 |

## Layout

```
config/            settings package, root URLconf, WSGI/ASGI entrypoints
core/              shared models, permissions, pagination, error handling
accounts/          User, roles, email verification, tokens, password reset
providers/         provider profiles, services, availability, discovery
bookings/          appointments and their line items
reviews/           ratings and comments
payments/          Razorpay orders and webhook
tests/             pytest suite
```

## Running it

```bash
cp .env.example .env          # then fill in at least SECRET_KEY
uv sync --all-groups
createdb barbershop
psql barbershop -c 'CREATE EXTENSION IF NOT EXISTS postgis;'
uv run python manage.py migrate
uv run python manage.py runserver
```

- API — <http://127.0.0.1:8000/api/v1/>
- Admin — <http://127.0.0.1:8000/admin/>
- OpenAPI UI — <http://127.0.0.1:8000/api/v1/docs/>
- Health — <http://127.0.0.1:8000/healthz>

## Docker

```bash
docker compose up -d db              # database only, run the API on your host
docker compose up --build api        # the API in a container
docker compose run --rm test         # pytest inside the container
```

## Checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy .
uv run pytest
```

All three run in CI on every push.

## Settings

`DJANGO_SETTINGS_MODULE` selects one of:

| Module                        | Used for                            |
| ----------------------------- | ----------------------------------- |
| `config.settings.dev`         | local development (the default)     |
| `config.settings.test`        | the pytest suite                    |
| `config.settings.prod`        | production — refuses to boot unconfigured |

Every value is read through `config/env.py`, which coerces types and fails loudly
on a missing required variable rather than letting `None` reach the database.