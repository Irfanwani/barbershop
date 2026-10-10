# Architecture

## The shape of the system

```
┌──────────────────────────────────────────────┐
│              apps/mobile  (Expo)             │
│                                              │
│   expo-router · TanStack Query · Zustand     │
│                                              │
│      ┌───────────────┐  ┌───────────────┐    │
│      │ Customer mode │  │ Provider mode │    │
│      └───────────────┘  └───────────────┘    │
└──────────────────┬───────────────────────────┘
                   │ HTTPS · JSON
                   │ Authorization: Token <knox>
                   ▼
┌──────────────────────────────────────────────┐
│            services/api  (Django)            │
│                                              │
│  /api/v1/auth      /api/v1/providers         │
│  /api/v1/services  /api/v1/bookings          │
│  /api/v1/reviews   /api/v1/payments          │
│  /api/v1/me                                 │
│                                              │
│         django-rest-knox  ·  drf-spectacular  │
└────────┬──────────────────────┬──────────────┘
         │                      │
         ▼                      ▼
   ┌───────────┐          ┌──────────┐
   │PostgreSQL │          │   S3     │
   │  +PostGIS │          │  media   │
   └───────────┘          └──────────┘
                            Razorpay
```

## One app, two modes

The defining decision of this revamp. The old world had two React Native apps:

- **`barbershopui`** — the customer-facing app
- **`servicebarbershop`** — the app for salons and barbers

Users found this genuinely confusing: two listings, two accounts, two login flows, two
places for bugs to hide. The new app has a **role** on the user account, and the app
tailors itself to it.

| | Customer mode | Provider mode |
| --- | --- | --- |
| Entry point | Browse barbers near you | Today's schedule |
| Tab bar | Home · Bookings · Profile | Dashboard · Jobs · Services · Profile |
| Onboarding | Location + about you | Shop details, hours, staff count, bank account |
| Can book | yes | no |
| Can be reviewed | no | yes |

A user picks a role during onboarding and it is recorded on the account. Switching roles
is a support action, not a self-service toggle — it changes what data the account is
allowed to hold.

## Why the API is versioned

The previous backend served everything from unversioned paths (`/api/accounts/login`)
with two competing login endpoints returning two different payload shapes. Any change
broke installed apps that nobody could update.

Everything now lives under **`/api/v1/`**. When a breaking change comes, `/api/v2/`
arrives beside it and v1 gets a deprecation window. `/api/v1/` also means the
generated OpenAPI schema can evolve without clients pinning to old URLs.

## Auth

`django-rest-knox` issues opaque tokens. Clients send `Authorization: Token <key>`.

- Tokens live in the device's **secure enclave** via `expo-secure-store`, never in
  `AsyncStorage`.
- Default TTL is 7 days with sliding refresh.
- Every endpoint declares permissions explicitly. There is no global "allow all".

## Money

Prices are **never** accepted from a client. A booking request names services; the API
looks up each service's authoritative price, applies the platform commission, and
computes the total. The client is told the total, and its agreement is recorded. This
closes the single worst hole in the old backend, where a client could post any
`totalcost` they liked.

Razorpay handles card capture. A webhook confirms payment and flips the booking —
the client cannot mark its own booking as paid.

## Geospatial search

Provider locations are `PointField(geography=True, srid=4326)` in PostGIS. Search is a
single `ST_DWithin` + `ST_Distance` query, so "barbers within 5 km of me" is an index
hit rather than a table scan in Python.

## Data model at a glance

```
User ──┬── CustomerProfile (1:1)
       └── ProviderProfile (1:1)
                ├── Service (1:N)         what they sell, at what price
                ├── Booking (1:N)         who booked them, when
                └── Review (1:N)          1..5 stars + comment

Booking ── BookingItem (1:N)   snapshots service name + price at time of booking
```

A `BookingItem` snapshots the price. If a provider raises their prices next month,
yesterday's invoices do not silently change.

## Further reading

- [`docs/DEVELOPMENT.md`](DEVELOPMENT.md) — running everything locally
- [`docs/decisions/`](decisions/) — architecture decision records
- [`docs/MIGRATION.md`](MIGRATION.md) — how the old repos map onto this one