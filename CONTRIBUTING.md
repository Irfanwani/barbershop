# Contributing to BarberShop

Thanks for helping improve BarberShop. This document covers the ground rules so that
contributions from anyone land cleanly.

## Repository layout

BarberShop is a monorepo. Please keep changes inside the service they belong to:

```
apps/mobile      React Native app (Expo). Touch this for anything user-facing.
services/api     Django REST API. Touch this for anything business-logic related.
docs             Architecture notes and ADRs.
```

If a change needs to move across both, open **two** pull requests and link them,
or make the change in two commits with a clear "backend half" / "app half" message.
This keeps each side independently reviewable and independently revertable.

## Ground rules

1. **Never commit secrets.** Every configurable value is read from the environment.
   `.env.example` documents what is needed; `.env` is gitignored.
2. **One concern per commit.** If you need two unrelated ideas, open two commits.
3. **Conventional Commits** for every commit message:

   ```
   <type>(<optional scope>): <imperative summary under 72 chars>
   ```

   Valid types: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`,
   `ci`, `chore`, `revert`, `style`.

   ```
   feat(api): add slot-availability endpoint for providers
   fix(app): stop booking slots that are already in the past
   chore: bump ruff to 0.14
   ```

4. **Tests accompany behaviour changes.** A bug fix without a regression test is
   incomplete. New endpoints need request-level tests; new UI needs at least a
   render or hook test.

## Before you open a pull request

```bash
make test       # every test suite
make lint       # ruff + eslint
make typecheck  # mypy + tsc
```

CI runs the same three commands, so a green local run means a green build.

## Adding a dependency

```bash
cd services/api && uv add <package>      # runtime
cd services/api && uv add --dev <package>  # tooling
cd apps/mobile  && yarn add <package>
cd apps/mobile  && yarn add -D <package>
```

Commit the updated lockfile (`uv.lock` / `yarn.lock`) with the change. Never edit a
lockfile by hand.

## Database changes

1. Change the model.
2. `make api-makemigrations`
3. Read the generated migration. **Always** — Django gets it wrong often enough that
   blindly committing it is how production databases get wrecked.
4. Never edit a migration that has already been merged into `main`.