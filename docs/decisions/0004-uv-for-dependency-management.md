# 0004. `uv` for dependency management

- **Status**: Accepted
- **Date**: 2026-10-10

## Context

`barbershopbackend` carried two dependency manifests that disagreed with each other:

| Package             | `pyproject.toml` | `requirements.txt` |
| ------------------- | ---------------- | ------------------ |
| Django              | `>=4.0.3`        | `>=4.1.4`          |
| DRF                 | `>=3.13.1`       | `>=3.14.0`         |
| psycopg2            | `psycopg2-binary` | `psycopg2`        |
| django-storages     | `^1.13.2`        | **absent**         |
| boto3               | `^1.26.104`      | **absent**         |
| autopep8, pycodestyle | runtime deps   | runtime deps       |

`django-storages` and `boto3` are imported by `barbershop/storage_backends.py` and were
missing from `requirements.txt` entirely, so a build using that file would have failed
at import time. Meanwhile `.gitignore` excluded `poetry.lock`, so no build was
reproducible — each one resolved to whatever was newest.

Two formatters were also installed as runtime dependencies, because Poetry had no dev
group configured.

## Decision

Drop both manifests. One `pyproject.toml` with PEP 621 metadata and `uv` as the
resolver. `uv.lock` is committed, which makes every build reproducible and lets CI
detect dependency drift.

Development tooling moves into `[dependency-groups] dev`, where it belongs. Tooling
that runs only in CI gets its own `ci` group so production images stay small.

## Consequences

**Good**

- `uv.lock` committed means "works on my machine" stops being a class of bug.
- A missing dependency is impossible to miss — the lockfile is generated from the same
  `pyproject.toml` that declares imports, and `uv sync` fails loudly.
- `uv sync` is fast enough that there is no excuse for a stale virtualenv.

**Bad**

- Poetry-specific `[[tool.poetry.group]]` syntax is gone, so existing contributor
  habits do not transfer.
- `uv.lock` must be regenerated whenever `pyproject.toml` changes. CI enforces this by
  failing if `uv sync --locked` reports drift.

**Alternatives rejected**

- *Keep Poetry, add a lockfile, delete `requirements.txt`.* Also correct, and a smaller
  diff. `uv` was chosen because it resolves markedly faster and is already the
  direction the ecosystem is moving.
- *Pin exact versions in `requirements.txt` by hand.* Hand-maintained lockfiles drift
  and nobody reads the diffs.