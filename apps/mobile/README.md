# BarberShop mobile app

The customer and provider app. One codebase, two modes: a customer books and
pays, a provider takes bookings, manages staff and sees their earnings. Which
one you get is decided at sign-up and by the account's role, not by a build
flavour — see [ADR 0001](../../docs/decisions/0001-single-app-two-modes.md).

Expo + expo-router + React Native + TypeScript. 40 screens.

## Prerequisites

- Node 22+
- The [API](../../services/api/README.md) running on `http://127.0.0.1:8000`
- For device builds: the Expo Go app, or Xcode / Android Studio for a native build

## Running it

```bash
npm ci
npm start          # Expo dev server; press i / a, or scan the QR with Expo Go
npm run ios        # build and run on an iOS simulator
npm run android    # build and run on an Android emulator
npm run web        # run in a browser, for a quick look
npm run start:dev  # dev-client build, if you have the dev client installed
```

## Pointing it at an API

The base URL comes from `EXPO_PUBLIC_API_URL`, defaulting to
`http://127.0.0.1:8000` (see `src/api/client.ts`):

```bash
EXPO_PUBLIC_API_URL=http://192.168.1.20:8000 npm start
```

It has to be a **LAN address, not `127.0.0.1`**, for a physical device —
`127.0.0.1` on a phone is the phone. Android emulators reach the host at
`10.0.2.2`; the API's default `ALLOWED_HOSTS` contains `*`, so it answers either
way, and `.env.example` lists `10.0.2.2` explicitly if you narrow it.

Any variable prefixed `EXPO_PUBLIC_` is compiled into the JS bundle. That is
fine for a base URL and wrong for a secret; nothing secret belongs in this app.

## Checks

```bash
npm run typecheck   # tsc --noEmit
npm run lint        # eslint
npm test            # jest
npx expo export --platform all --output-dir dist   # prove it bundles
```

All four run in CI. The export step is there because a screen can typecheck and
still fail to bundle on a missing asset or a bad import, and that otherwise only
shows up on a device.

282 tests over jest and Testing Library.

## Layout

```
app/                     expo-router routes, one file per screen
  (auth)/                register, login, verify email, forgot password
  (onboarding)/          first-run flow for both modes
  (customer)/            browse, book, waitlist, orders, saved shops, profile
  (provider)/            dashboard, calendar, staff, earnings, analytics, exports
  settings.tsx
src/
  api/                   client (fetch, auth, errors), endpoint map, query hooks
  components/            shared UI
  lib/                   money, weekdays, class names, query client, secure store
  store/                 auth state
  types/                 API response types
tests/                   jest suites
```

Route groups in parentheses do not appear in the URL. `(customer)` and
`(provider)` are separate stacks behind their own `_layout.tsx`, so signing out
of one cannot leave the other's history on the stack.

## Conventions worth knowing before you add a screen

**The server owns the numbers.** The app never computes a price, a balance, a
deposit or a discount — it renders what the API returned and asks again if it
needs to change. A client that recalculates a total is a client that will
disagree with the charge. See
[ADR 0003](../../docs/decisions/0003-server-authoritative-pricing.md).

**Paise, not rupees.** Money crosses the wire as an integer number of paise and
is formatted for display by `src/lib/money.ts`. Floats are never involved.

**Writes carry an idempotency key.** Anything that creates or pays goes through
`useIdempotentMutation` in `src/api/hooks.ts`, which is deliberately *not*
exported — the exported hooks that wrap it are `useCreateBooking`,
`useCreateTipOrder`, `useVerifyPayment`, `useCreateSeries` and `useStopSeries`.
Reach for one of those rather than a bare `useMutation`, so a retry after a
dropped connection reuses the same key instead of charging twice. The key is
derived from the operation, not generated per attempt; that is the whole point,
and it is why the helper stays private.

**Every endpoint goes in `src/api/endpoints.ts`.** That file is what the tests
assert against, so a route that is not in it is a route nothing checks.

## Adding a screen

1. Add the file under the relevant group in `app/`.
2. Add the endpoint to `src/api/endpoints.ts` and a hook to `src/api/hooks.ts`.
3. Add the response type to `src/types/`.
4. Add a test. `tests/endpoints.test.ts` covers endpoint wiring;
   `tests/components.test.tsx` covers shared UI.

## Deep links

The custom scheme is `barbershop://` (`app.json`), and push notifications carry
a `screen` in their data payload. `destinationFor()` in `src/api/endpoints.ts`
maps a payload to a route — extend it rather than branching in the notification
handler, so the mapping stays testable. Note it takes the user as well: the same
notification lands a customer and a provider on different screens.

## Before a release

```bash
npm run typecheck && npm run lint && npm test
npx expo export --platform all --output-dir dist
```

There is no `eas.json` checked in, so build profiles are configured per
project. Bundle identifiers are `com.barbershop.app` on both platforms — change
them before shipping anything real, since the store listings are keyed to them.
