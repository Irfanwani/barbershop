# ---------------------------------------------------------------------------
# BarberShop monorepo
# ---------------------------------------------------------------------------
.DEFAULT_GOAL := help
.PHONY: help setup setup-api setup-app dev-api dev-app test test-api test-app \
        lint lint-api lint-app typecheck format clean \
        api-shell api-migrate api-makemigrations api-superuser app-lint app-typecheck

SHELL := /bin/bash

API_DIR := services/api
APP_DIR := apps/mobile
WEB_DIR := apps/web

help: ## Show this help
	@echo ""
	@echo "  ✂️  BarberShop monorepo"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""

# --- setup ------------------------------------------------------------------

setup: setup-api setup-app setup-web ## Install dependencies for every service

setup-api: ## Install backend dependencies (uv sync)
	@cd $(API_DIR) && uv sync --all-extras

setup-app: ## Install app dependencies
	@cd $(APP_DIR) && npm install

setup-web: ## Install website dependencies (tests only; the site has no build)
	@cd $(WEB_DIR) && npm install

# --- development ------------------------------------------------------------

dev-api: ## Run the API with autoreload on :8000
	@cd $(API_DIR) && uv run python manage.py runserver

dev-app: ## Start the Expo dev server
	@cd $(APP_DIR) && npm start

dev-web: ## Serve the marketing site on :4173
	@cd $(WEB_DIR) && npm start

api-shell: ## Open a Python shell with the Django context loaded
	@cd $(API_DIR) && uv run python manage.py shell

api-migrate: ## Apply database migrations
	@cd $(API_DIR) && uv run python manage.py migrate

api-makemigrations: ## Generate new migrations for changed models
	@cd $(API_DIR) && uv run python manage.py makemigrations

api-superuser: ## Create a Django superuser
	@cd $(API_DIR) && uv run python manage.py createsuperuser

api-seed: ## Fill the database with demo providers, customers and bookings
	@cd $(API_DIR) && uv run python manage.py seed_demo

api-schema: ## Regenerate the committed OpenAPI schema
	@cd $(API_DIR) && uv run python manage.py dump_schema

api-schema-check: ## Fail if the committed OpenAPI schema is stale
	@cd $(API_DIR) && uv run python manage.py dump_schema --check

# --- quality ----------------------------------------------------------------

test: test-api test-app test-web ## Run every test suite

test-api: ## Run the backend test suite
	@cd $(API_DIR) && uv run pytest

test-web: ## Run the website test suite
	@cd $(WEB_DIR) && npm test

test-app: ## Run the app test suite
	@cd $(APP_DIR) && npm test

lint: lint-api lint-app ## Lint the backend and the app

lint-api: ## Lint the backend with ruff
	@cd $(API_DIR) && uv run ruff check . && uv run ruff format --check .

lint-app: ## Lint the app with eslint
	@cd $(APP_DIR) && npm run lint

typecheck: ## Typecheck every service

typecheck-api:
	@cd $(API_DIR) && uv run mypy .

typecheck-app:
	@cd $(APP_DIR) && npm run typecheck

format: ## Auto-format the backend
	@cd $(API_DIR) && uv run ruff format . && uv run ruff check --fix .

# --- housekeeping -----------------------------------------------------------

clean: ## Remove build artefacts and caches
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf $(API_DIR)/.pytest_cache $(API_DIR)/.mypy_cache $(API_DIR)/.ruff_cache
	@echo "cleaned."