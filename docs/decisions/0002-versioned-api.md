# 0002. Version the API under `/api/v1/`

- **Status**: Accepted
- **Date**: 2026-10-10

## Context

The old backend served everything from unversioned paths — `/api/accounts/login`,
`/api/haircut/appointments` — and, in one case, shipped **two** login endpoints at
`/api/accounts/login` and `/api/accounts/login/` that returned different payload shapes
and disagreed about whether an account was a barber. There was no schema, no generated
client, and no way to change a response without breaking an installed app.

Meanwhile the URL told you nothing about what the resource *is*. `/api/accounts/`
returned users, shop details, bank details, service catalogues and geospatial search
results.

## Decision

Everything lives under **`/api/v1/`**, grouped by resource, and the schema is generated
by drf-spectacular:

```
/api/v1/auth/{register,login,logout,logout-all,verify-email,password-reset}/
/api/v1/me/
/api/v1/providers/
/api/v1/providers/me/{,bank/,services/}
/api/v1/bookings/
/api/v1/reviews/<pk>/
/api/v1/payments/{orders/,webhook/}
/api/v1/docs/  /api/v1/schema/
```

Plural nouns for collections, the resource name for singles. When a breaking change
lands, `/api/v2/` appears beside v1 and v1 keeps serving until clients have migrated.

The published OpenAPI schema is treated as a contract: it is generated in CI, and a
breaking change that is not accompanied by a version bump is a bug.

## Consequences

**Good**

- Non-breaking additions ship without ceremony; breaking ones are a deliberate act.
- The schema is the contract, so the mobile client can be typed from it.
- URLs describe resources, so `POST /api/v1/providers/` for search reads correctly and
  does not need a verb.

**Bad**

- Every deployed app from before the revamp stops working at the cutover. Mitigated by
  shipping the new app as a fresh listing rather than an in-place upgrade.
- Two login endpoints existed and clients used whichever they were written against;
  consolidating them meant re-verifying both flows by hand.

**Alternatives rejected**

- *Leave paths, add a `/v1` alias.* Leaves the confusing legacy surface alive indefinitely
  and gives new work two places to put things.
- *Move to GraphQL.* Solves over- and under-fetching for the app, but the geospatial
  search and the payment flow are both shaped badly for GraphQL, and it would have
  meant rewriting both clients against a second API.