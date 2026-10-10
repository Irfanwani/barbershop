# syntax=docker/dockerfile:1
#
# Multi-stage build for the BarberShop API.
#
#   docker build -t barbershop-api -f Dockerfile .
#   docker run --env-file .env -p 8000:8000 barbershop-api
#
# The image is built in three stages so that neither the compiler toolchain nor
# uv's cache ships to production.

# ---------------------------------------------------------------------------
# Stage 1 — resolve dependencies into a self-contained virtualenv
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app

# Copied alone first so the (slow) dependency layer is cached until pyproject
# or the lockfile actually changes.
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --no-default-groups

# ---------------------------------------------------------------------------
# Stage 2 — runtime system dependencies
#
# GDAL, GEOS and PROJ are not optional: django.contrib.gis links against them, and
# a missing libgdal turns every geodjango import into an opaque ImportError.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq5 \
        gdal-bin \
        libgdal-dev \
        binutils \
        libproj-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Stage 3 — the application
# ---------------------------------------------------------------------------
FROM runtime AS app

RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

COPY --chown=app:app . /app

RUN mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app/staticfiles /app/media

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://localhost:8000/healthz || exit 1

# Render/Railway/Fly all read $PORT; default to 8000 for local use.
CMD exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-3}" \
    --threads "${WEB_THREADS:-2}" \
    --timeout "${WEB_TIMEOUT:-60}" \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    --capture-output