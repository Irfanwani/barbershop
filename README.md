<div align="center">

# ✂️ BarberShop

**The single home for the entire BarberShop platform — backend API and mobile app.**

[![CI](https://github.com/Irfanwani/barbershop/actions/workflows/ci.yml/badge.svg)](https://github.com/Irfanwani/barbershop/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## What is this?

BarberShop is a marketplace platform that connects **customers** looking for a barber,
salon or spa with **service providers** running those establishments.

This repository is a **monorepo** containing every part of the product:

```
barbershop/
├── apps/
│   ├── mobile/        React Native app (Expo SDK 54) — customers *and* providers
│   └── web/           The marketing site and knowledge base — Vite + React
├── services/
│   └── api/           Django + DRF REST API
├── docs/              Architecture notes, ADRs, development and migration guides
└── .github/           CI workflows
```

## Why one app?

BarberShop used to ship **two** React Native apps — one for customers, one for service
providers. That was confusing: two downloads, two logins, two sets of bugs, two
brands. There is now **a single app** that adapts to who you are. A user picks their
role at sign-up and the navigation, dashboard and data all reshape around it.

## Repository layout

| Path               | What it is                                                    | Stack                                    |
| ------------------ | ------------------------------------------------------------- | ---------------------------------------- |
| `apps/mobile`      | The mobile app for customers and service providers            | Expo SDK 54 · RN 0.81 · expo-router · TS |
| `apps/web`         | The public marketing site and knowledge base                   | Vite · React · TypeScript · Vitest |
| `services/api`     | REST API, business logic, geospatial barber search, payments  | Django 5.2 · DRF · PostGIS · PostgreSQL  |
| `docs`             | Architecture decisions, API usage, development and migration   | Markdown                                 |

Each has its own README with the setup steps and the conventions that are easy to
get wrong: [`services/api`](services/api/README.md) ·
[`apps/mobile`](apps/mobile/README.md) · [`apps/web`](apps/web/README.md).

Start with `services/api/README.md` if you have never run this before — the
PostGIS prerequisite fails in a way that does not mention PostGIS.

## Getting started

Everything is driven by a small set of `make` targets. Run `make help` to see them all.

```bash
git clone https://github.com/Irfanwani/barbershop.git
cd barbershop

make setup          # install backend, app and website dependencies
make dev-api        # run the Django API on http://127.0.0.1:8000
make dev-app        # run the Expo app on your simulator/device
make dev-web        # serve the marketing site on :4173

make lint           # ruff + eslint, all three services
make typecheck      # mypy + tsc, all three services
make test           # every test suite
```

`make lint` and `make typecheck` cover the backend, the app **and** the website.
CI runs the same set, so a green local run means the same thing a green CI run
means.

Detailed, per-service instructions live in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## Tech stack

**Backend** — Django 5.2 · Django REST Framework · django-rest-knox · PostGIS ·
PostgreSQL · Razorpay · Gunicorn · WhiteNoise · drf-spectacular

**Mobile** — Expo SDK 54 · React Native 0.81 · expo-router · TypeScript ·
TanStack Query · Zustand · NativeWind · expo-secure-store

**Website** — Vite and React, with a searchable knowledge base covering the whole product
step. Deployable to anything that serves files.

## Quality gates

Every push runs [`ci.yml`](.github/workflows/ci.yml), which will:

- lint and typecheck the API with **ruff** and **mypy**
- run the **pytest** suite against a throwaway PostGIS database
- typecheck, lint and test the app with **tsc**, **eslint** and **Jest**, then
  bundle it for iOS, Android and web — a missing asset only shows up otherwise
- test the site and check every asset it references is actually served
- generate the **OpenAPI** schema and fail if the committed copy is stale

## Archived repositories

This platform was three separate repositories until 2026. They are archived and
read-only; their history and issues are intact.

| Repository                                                        | Now                                          |
| ---------------------------------------------------------------- | -------------------------------------------- |
| [`servicebarbershop`](https://github.com/Irfanwani/servicebarbershop) | The app, and the source of the branding.   |
| [`barbershopui`](https://github.com/Irfanwani/barbershopui)         | The separate provider app.                   |
| [`barbershopbackend`](https://github.com/Irfanwani/barbershopbackend) | The backend; its git history is preserved in `services/api`. |

Moving production data across is covered in
[`docs/MIGRATION.md`](docs/MIGRATION.md). The migration is one-way by design —
the legacy schema stored post-commission prices and had no booking lifecycle,
so there is no faithful way to write it back.

## Contributing

Please read [`CONTRIBUTING.md`](CONTRIBUTING.md). Commits follow
[Conventional Commits](https://www.conventionalcommits.org/).

## License

[MIT](LICENSE) © Irfan Wani