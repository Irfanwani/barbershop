# Local development

Prerequisites:

| Tool           | Version | Notes                                              |
| -------------- | ------- | -------------------------------------------------- |
| Python         | 3.12    | managed automatically by `uv`                       |
| Node           | 20+     | 22 LTS recommended                                  |
| Yarn           | 1.22    | the repo uses Yarn 1                               |
| PostgreSQL     | 15+     | with the **PostGIS** extension available            |
| GDAL / GEOS    | 3.8+    | only needed for local PostGIS work                  |

> If you would rather not install PostGIS locally, use the Docker Compose setup in
> [Using Docker](#using-docker) below.

## First run

```bash
git clone https://github.com/Irfanwani/barbershop.git
cd barbershop
make setup
```

## The API

### Environment

```bash
cd services/api
cp .env.example .env
$EDITOR .env        # at minimum set SECRET_KEY and POSTGRES_PASSWORD
```

Generate a real secret key:

```bash
uv run python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

### Database

The API needs a PostGIS-enabled PostgreSQL. Create one:

```bash
createdb barbershop
psql barbershop -c 'CREATE EXTENSION IF NOT EXISTS postgis;'
```

Then point `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` in `.env` at it and:

```bash
make api-migrate
make api-superuser
```

### Run it

```bash
make dev-api
```

- API root — <http://127.0.0.1:8000/api/v1/>
- Django admin — <http://127.0.0.1:8000/admin/>
- OpenAPI UI — <http://127.0.0.1:8000/api/v1/docs/>
- Raw schema — <http://127.0.0.1:8000/api/v1/schema/>

### Seed demo data

```bash
cd services/api && uv run python manage.py seed_demo
```

This creates a handful of providers, services and bookings so the app has something to
show the moment you open it.

### Tests

```bash
make test-api
```

Tests use `pytest` and Django's test runner. A real PostGIS database is required —
PostGIS-specific behaviour (distance queries) cannot be meaningfully tested against
SQLite. Set `TEST_POSTGRES_DB` if you want the suite to use something other than
`test_barbershop`.

## The app

```bash
cd apps/mobile
cp .env.example .env
$EDITOR .env     # set EXPO_PUBLIC_API_URL to your machine's LAN IP, not localhost
```

> **Important:** on a physical device `localhost` points at the phone, not your
> machine. Use your LAN address (e.g. `http://192.168.1.20:8000`). The Android
> emulator uses `http://10.0.2.2:8000`.

```bash
make dev-app
```

Then press `a` for Android, `i` for iOS, or scan the QR code with Expo Go.

### Checks

```bash
cd apps/mobile
yarn typecheck     # tsc --noEmit
yarn lint          # eslint
yarn test          # jest
```

## Using Docker

For the API database only — the app still runs on your host so hot reload works:

```bash
cd services/api
docker compose up -d db
make api-migrate
make dev-api
```

To run the API itself in a container:

```bash
docker compose up --build api
```

## Troubleshooting

**`ImproperlyConfigured: settings.SECRET_KEY`** — you skipped `cp .env.example .env`.

**`connection to server at "localhost", port 5432 failed`** — Postgres is not running,
or `POSTGRES_*` in `.env` does not match the local instance. `make test-api` creates
its own `test_barbershop` database; you need permission to create databases.

**App shows "Network request failed"** — the device cannot reach the API. Check that
`EXPO_PUBLIC_API_URL` uses your LAN IP, that the phone is on the same Wi-Fi, and that
your firewall allows port 8000. `adb reverse tcp:8000 tcp:8000` also works for
Android over USB.

**`Unsupported class field` / native build errors after `yarn install`** — stale native
state. `cd apps/mobile && yarn start -c` resets the Metro cache; delete
`ios/`+`android/` and run `npx expo prebuild` if native files are out of sync.