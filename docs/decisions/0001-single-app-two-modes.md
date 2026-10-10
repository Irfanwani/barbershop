# 0001. One app, role-based modes

- **Status**: Accepted
- **Date**: 2026-10-10

## Context

BarberShop shipped as two React Native apps from three separate repositories:

- `barbershopui` — customer facing, plain JavaScript, Redux thunks, react-native-paper
- `servicebarbershop` — provider facing, TypeScript, Redux Toolkit Query, NativeBase

The two had shared no code and had drifted into different architectures. Users saw two
listings in the app store with confusingly similar names and icons, and had to pick
before they could even register. Anyone who wanted to do both — a customer on
weekends who runs a shop on weekdays — had to maintain two accounts, two passwords and
two sets of notifications.

Meanwhile every product change had to be written, reviewed, tested and shipped twice.

## Decision

Ship **one** app. The user account carries an explicit `role`, chosen at onboarding,
and the app renders a different experience for each:

- `customer` — browse providers, book, pay, review
- `provider` — manage shop details, services, bank account, bookings, reviews

Navigation is a route group per role (`app/(customer)/` and `app/(provider)/`), so the
two experiences share components, theme, networking and state while staying logically
separate.

The API mirrors this: a user has either a `CustomerProfile` or a `ProviderProfile`, and
the permissions on each endpoint make it impossible to mix them up.

## Consequences

**Good**

- One codebase, one test suite, one release train. Roughly half the maintenance.
- Users can be both, over time, without a second account.
- The API can stop inferring intent from "does this user happen to have a
  `BarberDetails` row?" and start stating it.

**Bad**

- The rewrite cost more than maintaining two apps would have, short-term. That cost is
  paid once; the old cost recurred forever.
- Role switching is a support action rather than a self-service toggle, because the
  data an account holds changes shape.
- The app binary is larger than either old app and carries code for both modes.

**Alternatives rejected**

- *Keep two apps, share a component library.* Still two downloads and two accounts.
  Solves the code duplication but none of the user confusion.
- *One app, no roles, hide provider UI behind a flag.* Avoids the onboarding choice but
  leaves the data model ambiguous, which is what made the old API hard to reason about.