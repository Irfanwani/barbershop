# Migration guide

How the three repositories that BarberShop grew out of map onto this monorepo, and
what changed.

## Where everything went

| Old repository                              | New home            | Fate                          |
| ------------------------------------------- | ------------------- | ----------------------------- |
| [`barbershopbackend`](https://github.com/Irfanwani/barbershopbackend) | `services/api` | rewritten, history preserved |
| [`servicebarbershop`](https://github.com/Irfanwani/servicebarbershop)  | `apps/mobile` | superseded, branding kept    |
| [`barbershopui`](https://github.com/Irfanwani/barbershopui)            | `apps/mobile` | superseded, screens ported    |

All three legacy repositories are **archived** and read-only. Nothing was deleted —
their full history is intact and reachable.

## Backend

### Versions

| Package              | Before       | Now       |
| -------------------- | ------------ | --------- |
| Python                | 3.10+        | 3.12      |
| Django                | >=4.0.3 (unpinned, no lockfile) | 5.2, locked |
| DRF                   | >=3.13.1 (unpinned)             | 3.16, locked |
| Dependency management | Poetry **and** `requirements.txt`, disagreeing | `uv` with a committed `uv.lock` |
| Tests                 | three empty stub files | pytest suite covering auth, providers, services, bookings, reviews, payments |

The old repo had two dependency manifests that pinned different versions of Django,
DRF, Pillow, requests and psycopg2, and `.gitignore`d its Poetry lockfile — so every
build resolved to whatever was newest that day. That is now a single `pyproject.toml`
plus a committed `uv.lock`.

### URLs

Everything moved under `/api/v1/`, and the two competing login endpoints are now one.

| Old                                            | New                              |
| ---------------------------------------------- | -------------------------------- |
| `POST /api/accounts/login/` (knox)             | `POST /api/v1/auth/login/`       |
| `POST /api/accounts/login` (custom)            | `POST /api/v1/auth/login/`       |
| `POST /api/accounts/register`                  | `POST /api/v1/auth/register/`    |
| `GET/POST /api/accounts/verifyemail`           | `GET/POST /api/v1/auth/verify-email/` |
| `POST/PUT /api/accounts/passwordreset`         | `POST/PUT /api/v1/auth/password-reset/` |
| `POST /api/accounts/logout/`                   | `POST /api/v1/auth/logout/`      |
| `POST /api/accounts/logoutall/`                | `POST /api/v1/auth/logout-all/`  |
| `DELETE /api/accounts/deleteuser/<pk>`         | `DELETE /api/v1/me/`             |
| `GET /api/accounts/authenticateuser`           | `GET /api/v1/me/`                |
| `POST/PUT /api/accounts/userdetails`           | `PUT /api/v1/me/profile/`        |
| `POST/PUT /api/accounts/barberdetails`         | `PUT /api/v1/providers/me/`      |
| `POST /api/accounts/createbank`                | `PUT /api/v1/providers/me/bank/` |
| `GET/POST/PUT/DELETE /api/accounts/addservices`| `GET/POST/PATCH/DELETE /api/v1/providers/me/services/` |
| `POST /api/accounts/filterbarbers`             | `GET /api/v1/providers/`         |
| `GET /api/accounts/getbarber/<pk>`             | `GET /api/v1/providers/<pk>/`    |
| `GET /api/accounts/getuser/<pk>`               | `GET /api/v1/users/<pk>/`        |
| `GET/POST /api/haircut/appointments`           | `GET/POST /api/v1/bookings/`     |
| `DELETE /api/haircut/cancelappointment/<pk>`   | `DELETE /api/v1/bookings/<pk>/`  |
| `GET/POST/DELETE /api/haircut/reviews`         | `GET/POST /api/v1/providers/<pk>/reviews/`, `DELETE /api/v1/reviews/<pk>/` |
| `POST/PUT /api/haircut/savetoken`,`removetoken`| `POST/DELETE /api/v1/me/push-tokens/` |
| `POST/PUT /api/payments/createorder`           | `POST /api/v1/payments/orders/`, webhook endpoint |

### Security fixes

The old API had several issues that a revamp should not carry forward:

- **Any authenticated user could mark any booking as paid.** `PUT /payments/createorder`
  took an arbitrary appointment id and set `paid=True` on it. Now payment state is only
  ever changed by a verified Razorpay webhook.
- **Any authenticated user could rewrite any service's price.** The service update took
  an id and an amount with no ownership check.
- **Bookings trusted the client's price.** `totalcost` and `services` were stored
  exactly as posted. The server now prices the booking itself.
- **Bookings trusted the client's clock.** The "is this slot in the future?" check used
  a `currentdatetime` value supplied by the phone.
- **Exact store coordinates were readable by any authenticated user** via
  `getbarber/<pk>`. Public provider responses now carry approximate coordinates only.
- **Bank account numbers were stored and returned in plaintext.** Account numbers are
  now encrypted at rest and masked in every serializer.
- **Verification codes were generated with `random`.** That is a Mersenne Twister —
  predictable. Codes now come from `secrets`.
- **No rate limiting.** Login, registration and password reset are now throttled.
- **Bare `except:` around everything**, which converted real bugs into generic 400s.

## Mobile app

`servicebarbershop` and `barbershopui` were both Expo 47 / RN 0.70.5 apps, one in plain
JavaScript with Redux thunks and react-native-paper, the other in TypeScript with Redux
Toolkit Query and NativeBase. They had drifted into two entirely different architectures
and shared almost no code.

`apps/mobile` is a **new app** built on Expo SDK 54 / RN 0.81 with expo-router. Every
screen from both old apps was carried across and cleaned up; the **branding — icons,
launcher images, splash screens, illustration SVGs — came from `servicebarbershop`**,
which is the more polished of the two.

### Removed dependencies

`axios` (replaced by a typed `fetch` client), `form-data` + `mime` (React Native's
`FormData` and `Blob` are sufficient), `react-native-alert-pro`, `react-native-bouncy-checkbox`,
`react-native-raw-bottom-sheet`, `react-native-ratings`, `react-native-razorpay`
(you need the native Razorpay SDK for a real payment sheet), `redux-persist`
(replaced by Zustand's own persistence), `react-native-paper` and `native-base`.

## Mapping old concepts to new

| Old                            | New                                    |
| ------------------------------ | -------------------------------------- |
| `UserDetails` / `BarberDetails` | `CustomerProfile` / `ProviderProfile`  |
| `ServicesDetails`              | `Service`                              |
| `Appointments`                 | `Booking` + `BookingItem`              |
| `RatingsAndReviews`            | `Review`                               |
| `NotificationTokens`           | `PushToken`                            |
| implicit `is_barber` flag      | explicit `User.role`                   |
| `services` pipe-delimited string on the booking | `BookingItem` rows        |
| two apps                       | one app, two modes                     |