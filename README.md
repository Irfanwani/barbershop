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
│   └── mobile/        React Native app (Expo SDK 54) — customers *and* providers
├── services/
│   └── api/           Django + DRF REST API
├── docs/              Architecture notes, ADRs, API reference
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
| `services/api`     | REST API, business logic, geospatial barber search, payments  | Django 5.2 · DRF · PostGIS · PostgreSQL  |
| `docs`             | Architecture decisions, API usage, local development guide    | Markdown                                 |

## Getting started

Everything is driven by a small set of `make` targets. Run `make help` to see them all.

```bash
git clone https://github.com/Irfanwani/barbershop.git
cd barbershop

make setup          # install backend + app dependencies
make dev-api        # run the Django API on http://127.0.0.1:8000
make dev-app        # run the Expo app on your simulator/device
```

Detailed, per-service instructions live in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## Tech stack

**Backend** — Django 5.2 · Django REST Framework · django-rest-knox · PostGIS ·
PostgreSQL · Razorpay · Gunicorn · WhiteNoise · drf-spectacular

**Mobile** — Expo SDK 54 · React Native 0.81 · expo-router · TypeScript ·
TanStack Query · Zustand · NativeWind · expo-secure-store

## Quality gates

Every push runs [`ci.yml`](.github/workflows/ci.yml), which will:

- lint and typecheck the API with **ruff** and **mypy**
- run the **pytest** suite against a throwaway PostGIS database
- typecheck and lint the app with **tsc** and **eslint**
- generate and validate the **OpenAPI** schema

## Contributing

Please read [`CONTRIBUTING.md`](CONTRIBUTING.md). Commits follow
[Conventional Commits](https://www.conventionalcommits.org/).

## License

[MIT](LICENSE) © Irfan Wani