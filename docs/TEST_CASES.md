# Test Case Sheet

Every automated test in the repository, organised by roadmap section and by part
(backend / web / app), plus the live checks that cannot be automated because they
need real credentials.

- **Backend** — `services/api` (Django + DRF), 1218 tests
- **App** — `apps/mobile` (React Native / Expo), 282 tests
- **Web** — `apps/web` (Vite marketing site), 47 tests
- **Total** — **1547 automated tests**

Counts below are taken from the suites themselves, not estimated.

---

## Running the suites

```bash
# Backend — 1218 tests, ~60s. Drop --reuse-db to rebuild the test database,
# which is what CI does and what proves migrations apply from scratch.
cd services/api && uv run pytest --reuse-db

# App
cd apps/mobile && npm test

# Web
cd apps/web && npm test
```

Full CI gate for the backend, all of which passed at the time of writing:

```bash
cd services/api
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run mypy .                  # types
uv run pytest                  # tests + coverage floor of 85%
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check --deploy
```

---

## Coverage by section

Feature sections map to `TODOS.md`. Counts are tests, not files.

| Section | Feature | Backend | App | Web | Total |
|---|---|---:|---:|---:|---:|
| P0.1 | Marketing site shop list | – | – | 26 | 26 |
| P0.2 | Site does not advertise absent features | – | – | 21 | 21 |
| P1.1 | Deposits on long services | 49 | – | – | 49 |
| P1.2 | Cancellation policy and late fee | 22 | – | – | 22 |
| P1.3 | Refunds | 38 | – | – | 38 |
| P1.4 | Payout ledger and withdrawal | 31 | – | – | 31 |
| P2.1 | Individual staff members | 28 | 21 | – | 49 |
| P2.2 | Waitlist with automatic fill | 29 | – | – | 29 |
| P2.3 | Rescheduling | 21 | – | – | 21 |
| P2.4 | Saved shops | 17 | – | – | 17 |
| P2.5 | Public booking link per shop | 28 | – | – | 28 |
| P3.1 | Loyalty points | 31 | 6 | – | 37 |
| P3.2 | Rebooking nudges | 18 | – | – | 18 |
| P3.3 | Recurring bookings | 28 | 7 | – | 35 |
| P3.4 | Referral programme | 27 | 8 | – | 35 |
| P3.5 | Push preferences synced to server | 12 | – | – | 12 |
| P3.6 | Two-way WhatsApp | 36 | 3 | – | 39 |
| P4.1 | Provider analytics | 21 | – | – | 21 |
| P4.2 | Consultation forms | 29 | 12 | – | 41 |
| P4.3 | Tips | 18 | 5 | – | 23 |
| P4.4 | Promo and discount codes | 27 | 4 | – | 31 |
| P4.5 | Review reminders and photo reviews | 47 | – | – | 47 |
| P5.1 | Idempotency keys | 18 | 4 | – | 22 |
| P5.2 | API keys | 24 | 12 | – | 36 |
| P5.3 | Abuse and no-show scoring | 28 | 8 | – | 36 |
| P5.4 | Provider CSV export | 25 | 9 | – | 34 |
| P5.5 | Observability | 37 | – | – | 37 |
| P5.6 | Timezone correctness | 21 | 4 | – | 25 |
| — | Cross-cutting foundations | 508 | 179 | – | 687 |
| | **Total** | **1218** | **282** | **47** | **1547** |

---

# Part 1 — Backend

## P1.1 Deposits on long services — 49 tests

`services/api/tests/test_deposits.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestCollectingTheBalance` | 12 | Balance is collected at the end, not up front |
| `TestComputeDeposit` | 6 | Deposit arithmetic and thresholds |
| `TestChargingADeposit` | 5 | Deposit is taken through the payment path |
| `TestAmountDue` | 4 | Remaining amount due after a deposit |
| `TestConstraints` | 4 | A deposit can never exceed the booking total |
| `TestDepositIsNotPayment` | 4 | Deposit does not mark the booking paid |
| `TestBookingCreation` | 4 | Deposit attached at creation |
| `TestDefaultKind` | 3 | Default deposit kind |
| `TestRequestedKind` | 3 | Explicitly requested kind is honoured |
| `TestQuoteShowsDeposit` | 2 | Quote surfaces the deposit |
| `TestQuoteCarriesDeposit` | 2 | Same deposit arrives at checkout |

## P1.2 Cancellation policy and late fee — 22 tests

`services/api/tests/test_cancellation_policy.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestCancelling` | 11 | Cancellation by customer and provider, each side's effects |
| `TestCancellationDeadline` | 5 | The deadline boundary, including exactly on it |
| `TestPolicyIsFrozen` | 4 | Policy captured at booking time, not read live |
| `TestRefundable` | 2 | What is and is not refundable |

## P1.3 Refunds — 38 tests

`services/api/tests/test_refunds.py` (27), `tests/test_refund_reconciliation.py` (11)

| Class | Tests | Covers |
|---|---:|---|
| `TestSendRefund` | 11 | Refund issued for the right amount, through the gateway |
| `TestCancellationRefund` | 7 | Cancellation triggers the correct refund |
| `TestRefundBooking` | 6 | Refund is tied to a booking, not a customer |
| `TestReconciliation` | 3 | Ledger and gateway agree |
| `TestMoneyThatWentBack` | 6 | Money movement is reflected in balances |
| `TestTheRefundWebhook` | 5 | Refund webhook is genuine and idempotent |

## P1.4 Payout ledger and withdrawal — 31 tests

`services/api/tests/test_ledger.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestWithdrawal` | 10 | Withdrawal against cleared balance only |
| `TestBalance` | 9 | Balance derived from the append-only ledger |
| `TestBalanceEndpoint` | 4 | Balance endpoint returns the right figures |
| `TestEarning` | 4 | Earnings credited once, not twice |
| `TestSettlement` | 4 | Settlement moves pending to cleared |

## P2.1 Individual staff members — 28 backend + 21 app = 49

`services/api/tests/test_staff.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestEndpoints` | 10 | CRUD, ownership, deletion |
| `TestCapacity` | 5 | A chair cannot be double-booked |
| `TestValidation` | 4 | Staff record validation |
| `TestChoosingSomeoneClosed` | 4 | Closed staff member cannot be booked |
| `TestOnePersonCannotBeTwoPlaces` | 3 | Overlapping shifts rejected |
| `TestTheMigration` | 2 | Data migration from the old shape |

`apps/mobile/tests/weekdays.test.ts` — working-hours construction and validation

| Suite | Tests | Covers |
|---|---:|---|
| `validateWeek` | 7 | Rejects malformed weeks |
| `buildWeek` | 6 | Builds a week from defaults |
| `defaultDay` | 3 | Default day shape |
| `weekday numbering` | 2 | Numbering matches the server's |
| `toApiDays` | 2 | Conversion to the API's day format |
| `openDayCount` | 1 | Counts open days |

## P2.2 Waitlist with automatic fill — 29 tests

`services/api/tests/test_waitlist.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestAFreedSlotIsOffered` | 9 | A cancelled slot is offered to the next in line |
| `TestOffersExpire` | 7 | An unanswered offer lapses and the slot returns |
| `TestResponding` | 7 | Accept declines the offer for everyone else |
| `TestJoining` | 6 | Joining, leaving, duplicate joins |

## P2.3 Rescheduling — 21 tests

`services/api/tests/test_reschedule.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestMoving` | 7 | The ordinary move |
| `TestRefusals` | 5 | Moves that must be refused |
| `TestTheCancellationWindowStillApplies` | 5 | Late-window rules survive a move |
| `TestPriceChanges` | 4 | A price change stops the move until accepted |

## P2.4 Saved shops — 17 tests

`services/api/tests/test_saved_shops.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestSaving` | 8 | Save and unsave, idempotent |
| `TestSavedShopsComeFirst` | 6 | Ordering |
| `TestAClosedShopIsStillSaved` | 3 | Saving survives a shop closing |

## P2.5 Public booking link per shop — 28 tests

`services/api/tests/test_public_surface.py` (14), `tests/test_shop_pages.py` (14)

| Class | Tests | Covers |
|---|---:|---|
| `TestAnonymousBrowsing` | 8 | Anonymous users can browse and book |
| `TestStillPrivate` | 5 | Customer data stays private |
| `TestAnonymousThrottling` | 1 | Anonymous access is rate limited |
| `TestThePage` | 8 | The rendered public page |
| `TestTheAddress` | 4 | Address on the page |
| `TestChangingTheAddress` | 2 | Address changes are reflected |

## P3.1 Loyalty points — 31 backend + 6 app = 37

`services/api/tests/test_loyalty.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestSpendingPointsOnABooking` | 8 | Redemption is applied server-side |
| `TestTheBalance` | 6 | Balance is correct after earn and spend |
| `TestTheEndpoints` | 5 | Balance and history endpoints |
| `TestExpiry` | 4 | Points expire |
| `TestRedemption` | 4 | Redemption cannot exceed the balance |
| `TestEarning` | 4 | Earning is once per booking |

`apps/mobile/tests/discounts.test.tsx` → `loyalty points` (6)

## P3.2 Rebooking nudges — 18 tests

`services/api/tests/test_reengagement.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestWhoIsLapsed` | 8 | The lapse window, per provider |
| `TestPreferences` | 4 | Opt-out is honoured |
| `TestSending` | 4 | The nudge is sent once |
| `TestTheTask` | 2 | Scheduled task behaviour |

## P3.3 Recurring bookings — 28 backend + 7 app = 35

`services/api/tests/test_recurring.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestStartingASeries` | 9 | First booking plus the series record |
| `TestTheDatesComeFromTheOrigin` | 5 | Occurrence dates derive from the original booking |
| `TestStoppingASeries` | 4 | Unbooked occurrences are cancelled, booked ones are not |
| `TestTheHorizon` | 3 | Materialisation horizon |
| `TestEachOccurrenceIsItsOwnBooking` | 3 | Occurrences are independently chargeable and cancellable |
| `TestTheEndpoint` | 3 | List and stop |
| `TestWhenTheShopStopsOfferingIt` | 1 | Deactivated service ends the series |

`apps/mobile/tests/recurring.test.tsx` → `regular visits` (7)

## P3.4 Referral programme — 27 backend + 8 app = 35

`services/api/tests/test_referrals.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestTheCode` | 5 | Code generation, uniqueness, format |
| `TestTheEndpoints` | 5 | Share and redeem endpoints |
| `TestItCreditsOnCompletionNotBooking` | 4 | Reward only on completion |
| `TestSameAccountAbuse` | 4 | Duplicate-account abuse blocked |
| `TestSelfReferral` | 3 | Self-referral blocked |
| `TestTheLedgerItself` | 2 | Referral ledger integrity |
| `TestAttribution` | 2 | Provider attribution |
| `TestACancelledReferral` | 2 | Cancellation lapses the reward |

`apps/mobile/tests/referrals.test.tsx` — `sharing your own code` (5), `entering somebody else's code` (3)

## P3.5 Push preferences synced to the server — 12 tests

`services/api/tests/test_notification_preferences.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestChanging` | 7 | Server is the source of truth |
| `TestReading` | 3 | Preferences round-trip |
| `TestTheReminderTaskCannotDisagree` | 2 | The task respects the stored preference |

## P3.6 Two-way WhatsApp — 36 backend + 3 app = 39

`services/api/tests/test_messaging.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestRepliesCancelTheBooking` | 14 | Reply words, including near-misses |
| `TestOneConfirmation` | 6 | Exactly one confirmation per booking |
| `TestTheMessageItself` | 4 | Manage link and content |
| `TestDeliveryStatus` | 4 | Status updates reconcile |
| `TestRetrying` | 3 | Failed sends retry |
| `TestTheWebhookIsGenuine` | 3 | Signature verification, replay |
| `TestWhenThereIsNoProvider` | 2 | Silent no-op when unconfigured |

`apps/mobile/tests/whatsapp.test.tsx` — `cancelling by WhatsApp reply` (3)

## P4.1 Provider analytics — 21 tests

`services/api/tests/test_analytics.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestTheEndpoint` | 5 | Window selection and authorisation |
| `TestRates` | 5 | Completion, no-show, rebooking rates |
| `TestTheWholeWindowNotOnePage` | 4 | Whole window scanned, not the first page |
| `TestComparison` | 3 | Previous-period comparison |
| `TestRevenue` | 3 | Revenue, tips and fees from the ledger |
| `TestPerService` | 1 | Per-service breakdown |

## P4.2 Consultation forms — 29 backend + 12 app = 41

`services/api/tests/test_consultation_forms.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestAnsweringAtBooking` | 7 | Answers captured at booking |
| `TestWhatMayNotBeAnswered` | 6 | Validation of unanswerable input |
| `TestAuthoring` | 6 | Form and question authoring |
| `TestWhoMayRead` | 5 | Sensitive answers visible only to the owning provider |
| `TestAnswersAreFrozen` | 3 | Wording and sensitivity frozen at booking time |
| `TestTheBookingIsStillABooking` | 2 | Answers do not change booking semantics |

`apps/mobile/tests/consultation-forms.test.tsx` — `asking the questions` (9), `reading the answers` (3)

## P4.3 Tips — 18 backend + 5 app = 23

`services/api/tests/test_tips.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestRecording` | 4 | Tip recorded against the right booking and provider |
| `TestTheProviderKeepsAllOfIt` | 3 | No platform fee on tips |
| `TestWhatTheProviderSees` | 3 | Tip appears in provider earnings |
| `TestWhatATipIsNot` | 3 | A tip is not a booking payment |
| `TestPaying` | 3 | Tip payment path |
| `TestAHalfFinishedTip` | 2 | Abandoned tip leaves no partial state |

`apps/mobile/tests/tipping.test.tsx` — `tipping a finished appointment` (5)

## P4.4 Promo and discount codes — 27 backend + 4 app = 31

`services/api/tests/test_promotions.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestValidity` | 9 | Window, service scope, minimum spend |
| `TestTheArithmetic` | 6 | Discount arithmetic and stacking rules |
| `TestAtCheckout` | 5 | Applied at checkout from the quote's inputs |
| `TestTheFee` | 3 | Fee is on the discounted subtotal |
| `TestAtQuote` | 3 | Same result at quote time |
| `TestTheClientCannotChoose` | 1 | A client-supplied discount is ignored |

`apps/mobile/tests/discounts.test.tsx` → `promo codes` (4)

## P4.5 Review reminders and photo reviews — 47 tests

`services/api/tests/test_reviews_api.py` (25)

| Class | Tests | Covers |
|---|---:|---|
| `TestCreate` | 12 | One review per booking, only by the customer |
| `TestList` | 5 | Listing and pagination |
| `TestDetailAndDelete` | 5 | Owner and staff deletion |
| `TestReply` | 3 | Provider reply |

`services/api/tests/test_review_requests.py` (22)

| Class | Tests | Covers |
|---|---:|---|
| `TestWhoGetsAsked` | 5 | Eligibility for being asked |
| `TestAskingForRemoval` | 5 | Removal request flow |
| `TestAskingOnce` | 3 | Never asked twice |
| `TestAnOptOutThatIsActuallyAnOptOut` | 2 | Opt-out stops reminders |
| `TestThePhotoIsActuallyOnThePage` | 2 | Photo renders on the public page |
| `TestPhotos` | 2 | Photo upload and validation |
| `TestTheTask` | 2 | The reminder task |
| `TestTheProviderHears` | 1 | Provider notified of the review |

## P5.1 Idempotency keys — 18 backend + 4 app = 22

`services/api/tests/test_idempotency.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestRetrying` | 5 | A retry returns the first result |
| `TestTheRaceTheRecordCannotSee` | 2 | Concurrent requests, one execution |
| `TestTheFingerprint` | 2 | Body change under the same key is refused |
| `TestTheSameKeyWithADifferentRequest` | 2 | Key reuse across operations refused |
| `TestAnExpiredKeyIsNotARecord` | 2 | Expired keys execute fresh |
| `TestTheWritesThatWereNotGuarded` | 2 | The guarded endpoints are the right ones |
| `TestOnlySuccessesAreRecorded` | 1 | Failures are not replayed |
| `TestTwoPeopleOnOneDevice` | 1 | Keys do not collide across users |
| `TestAnAncientKey` | 1 | Very old keys |

`apps/mobile/tests/idempotency.test.tsx` — `the key belongs to the operation, not the attempt` (4)

## P5.2 API keys — 24 backend + 12 app = 36

`services/api/tests/test_api_keys.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestManagingKeys` | 6 | Create, list, revoke |
| `TestTheKeyItself` | 6 | Hashed at rest, shown once |
| `TestReadCannotWrite` | 6 | Scope enforcement per endpoint |
| `TestRevocationIsImmediate` | 5 | Revoked key stops working at once |
| `TestOnePersonOnly` | 1 | Keys are per owner |

`apps/mobile/tests/api-keys.test.tsx` — `creating a key` (4), `the secret` (4), `revoking` (4)

## P5.3 Abuse and no-show scoring — 28 backend + 8 app = 36

`services/api/tests/test_risk.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestFlags` | 9 | Flag creation, severity, clearing |
| `TestTheProviderEndpoint` | 4 | Provider view of a customer's risk |
| `TestNotEnoughHistory` | 4 | Below the sample threshold, nothing is claimed |
| `TestTheArithmetic` | 4 | Rate and weight maths |
| `TestTheAcceptanceCase` | 3 | The documented acceptance example |
| `TestTheCachedProfile` | 2 | Cached profile matches recomputation |
| `TestCancellingIsNotTheSameAsNotTurningUp` | 2 | Cancellations excluded from no-show rate |

`apps/mobile/tests/risk.test.tsx` — `a customer with a poor record` (5), `a customer with no history` (2), `a clean record` (1)

## P5.4 Provider CSV export — 25 backend + 9 app = 34

`services/api/tests/test_exports.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestTheRequest` | 5 | Queued, not synchronous |
| `TestSendingIt` | 4 | Email delivery and the download link |
| `TestTheFileIsSafeToOpen` | 4 | Formula injection, newlines, Unicode |
| `TestEveryBookingNotJustTheFirstPage` | 4 | Whole period exported |
| `TestTheWholeJob` | 3 | Job end to end |
| `TestTheMoneyIsRight` | 3 | Revenue figures reconcile with the ledger |
| `TestClientsAreAggregated` | 1 | Client dataset |
| `TestDatesAreTheShopsOwn` | 1 | Export uses the shop's timezone |

`apps/mobile/tests/exports.test.tsx` — `asking for an export` (6), `previous exports` (3)

## P5.5 Observability — 37 tests

`services/api/tests/test_observability.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestJsonLogs` | 5 | One JSON object per line, request id, task id, exception |
| `TestRequestIds` | 5 | Generated, propagated, bounded, cleared |
| `TestAFailedRequestIsFindable` | 5 | The acceptance criterion, end to end |
| `TestRequestMetrics` | 5 | Rate by status class, path normalisation, bounded percentiles |
| `TestReminderAlert` | 4 | Thresholds, raised once, resolves |
| `TestRemindersAreActuallyMeasured` | 3 | A failed reminder is not counted as sent |
| `TestMetricsEndpoint` | 3 | Operational numbers exposed |
| `TestConversion` | 3 | Quotes and bookings counted separately |
| `TestDeliveryFailureEndpoint` | 2 | Failures recorded |
| `TestNoShowRate` | 2 | Withheld below a meaningful sample |

## P5.6 Timezone correctness — 21 backend + 4 app = 25

`services/api/tests/test_timezones.py`

| Class | Tests | Covers |
|---|---:|---|
| `TestWorkingHoursAreTheShopsClock` | 6 | Hours evaluated in the shop's zone |
| `TestTheShopCanSetItsZone` | 5 | Validated on write |
| `TestResolvingTheZone` | 4 | Shop → account → server fallback chain |
| `TestOpenNowFollowsTheSameChainTheShopPageDoes` | 3 | Search and page agree |
| `TestOpenNowSearch` | 2 | Open-now filtering |
| `TestStaffHireTheShopClockToo` | 1 | Staff inherit the shop's zone |

`apps/mobile/tests/shop-timezone.test.tsx` — `shop time zone` (4)

---

## Cross-cutting backend foundations — 508 tests

Not tied to one feature, but load-bearing for all of them.

| File | Tests | Class breakdown |
|---|---:|---|
| `test_models.py` | 73 | `TestBooking` 13, `TestMoney` 10, `TestUser` 10, `TestReview` 9, `TestProviderProfile` 8, `TestProviderPayout` 6, `TestSlotAvailability` 6, `TestVerificationCode` 5, `TestPayment` 4, `TestPushToken` 2 |
| `test_providers_api.py` | 64 | `TestProviderSearch` 13, `TestMyProvider` 9, `TestMyServices` 8, `TestWorkingHoursApi` 7, `TestPriceInsights` 6, `TestPayout` 5, `TestAcceptingBookingsToggle` 4, `TestProviderDetail` 4, `TestServicePriceIndex` 3, `TestAvailability` 3, `TestServiceTypes` 2 |
| `test_bookings_api.py` | 46 | `TestCreate` 21, `TestList` 6, `TestCancel` 5, `TestLifecycle` 5, `TestQuote` 4, `TestDetail` 4, module 1 |
| `test_auth_api.py` | 45 | `TestRegister` 10, `TestEmailVerification` 7, `TestLogin` 6, `TestMe` 5, `TestPasswordReset` 5, `TestCustomerProfile` 4, `TestPushTokens` 3, `TestLogout` 3, module 2 |
| `test_core.py` | 45 | `TestExceptionHandler` 9, `TestPermissions` 9, `TestEncryptedField` 8, `TestCodeHelpers` 5, `TestMask` 5, module 3, `TestPublicMediaStorage` 2, `TestPagination` 2, `TestMoneyHelpers` 2 |
| `test_catalog_api.py` | 42 | `TestOrderCreate` 13, `TestOrderLifecycle` 8, `TestCatalogue` 8, `TestShopShelf` 4, `TestOrderAccess` 4, `TestQuote` 3, `TestPopular` 2 |
| `test_ai.py` | 41 | `TestMatcherContainment` 8, `TestSummariseProvider` 6, `TestSuggestEndpoint` 6, `TestKeywordFallback` 5, `TestSummaryParsing` 5, `TestMatcherFailure` 4, `TestCandidates` 3, `TestRatingBreakdown` 2, `TestSummaryEndpoint` 2 |
| `test_tasks.py` | 33 | `TestExpiry` 9, `TestDailyReminders` 8, `TestWorkingHours` 6, `TestDeliverPush` 5, `TestSchedule` 3, `TestEveningReminders` 2 |
| `test_payments_api.py` | 30 | `TestWebhook` 11, `TestCreateOrder` 6, `TestSignatureHelpers` 5, `TestVerify` 4, `TestDetail` 3, module 1 |
| `test_legacy_migrations.py` | 29 | `TestBookingMigration` 14, `TestProfileMigration` 11, module 4 |
| `test_pricing.py` | 18 | `TestBand` 9, `TestPlausibility` 4, `TestServiceNameBands` 4, `TestByShopType` 1 |
| `test_seed_command.py` | 14 | `TestSeed` 14 |
| `test_openapi_schema.py` | 11 | module-level: schema currency, zero warnings, routing allow-list, no empty 2xx bodies |
| `test_performance.py` | 9 | `TestProviderSearchCost` 4, `TestAvailabilityCost` 2, `TestPaginationStability` 2, `TestBookingListCost` 1 |
| `test_smoke.py` | 8 | module-level: the app boots and the basics respond |

---

# Part 2 — Web (marketing site)

47 tests across `apps/web/tests/`.

## P0.1 The shop list — 26 tests

`tests/home.test.tsx` (13)

| Test | Covers |
|---|---|
| `ShopCard shows the name, meta and starting price` | Card contents |
| `ShopCard says when a shop is not taking bookings` | Closed state |
| `ShopCard says so when there are no reviews` | Empty reviews |
| `ShopCard shows a distance once there is an origin` | Distance with a location |
| `ShopCard falls back to an initial when there is no photo` | Missing photo |
| `ShopCard uses a real image when there is one` | Photo present |
| `PriceCard leads with the typical figure and shows the range` | Typical price and range |
| `PriceCard labels a thin sample honestly` | Thin sample wording |
| `PriceCard renders nothing for an unusable band` | Unusable band |
| `ShopList explains an empty platform rather than showing a blank` | Empty platform |
| `the page renders the hero and the live numbers` | Hero and stats |
| `the page shows the knowledge base link` | Knowledge base link |
| `when the API is down still renders the page and says what is missing` | API failure |

`tests/format.test.ts` (13)

| Test | Covers |
|---|---|
| `formatPaise converts paise to rupees` | Money formatting |
| `formatPaise refuses to invent a price` | Missing price |
| `describeBand calls a well-populated band typical` | Band description |
| `describeBand refuses to call a single shop typical` | Sample honesty |
| `describeBand pluralises a thin sample correctly` | Pluralisation |
| `describeBand returns nothing for a band with no median` | No median |
| `buildQuery drops empty values` | Query building |
| `buildQuery encodes values` | Encoding |
| `buildQuery copes with nothing at all` | Empty input |
| `distance measures a known distance` | Distance |
| `distance is zero for the same point` | Same point |
| `distance says nothing when there is no location to measure from` | No location |
| `distance formats a distance for a card` | Formatting |

## Knowledge base — 21 tests

`tests/knowledge.test.tsx`

| Test | Covers |
|---|---|
| `the content itself has entries at all` | Content is non-empty |
| `the content itself gives every group and section an id so links land` | Deep links resolve |
| `the content itself has no duplicate ids` | Unique anchors |
| `the content itself gives every entry a question and a real answer` | Entry shape |
| `the content itself never describes a shipped feature as unavailable` | **No false "coming soon"** |
| `the content itself documents every shipped capability affirmatively` | Affirmative documentation |
| `the content itself never promises a feature that does not exist` | **No false promises** |
| `search finds an answer by its question` | Search by title |
| `search finds an answer by a word someone would type` | Search by body |
| `search finds a no-show by how it is phrased` | Plain-language search |
| `search ranks a title match above a passing mention` | Ranking |
| `search returns nothing for a blank query` | Blank query |
| `search returns nothing rather than everything for a nonsense query` | No false matches |
| `audience filter hides provider-only content from customers` | Audience filter |
| `audience filter keeps shared sections for everyone` | Shared content |
| `the page lists the contents` | Table of contents |
| `the page answers a search and counts what it found` | Search results |
| `the page says so when a search finds nothing` | Empty search |
| `the page filters to providers` | Provider filter |
| `the page marks the active filter for assistive tech` | Accessibility |
| `the page returns to everything` | Clearing the filter |

The three tests marked in bold are the P0.2 fix: they fail if the site claims a
feature is unavailable when it ships, or promises one that does not exist.

---

# Part 3 — App (mobile)

282 tests across `apps/mobile/tests/`. Feature-specific suites are listed with
their roadmap sections above; the rest are foundations.

## Cross-cutting app foundations — 179 tests

`tests/endpoints.test.ts` (71)

| Suite | Tests | Covers |
|---|---:|---|
| `provider endpoints` | 24 | Every provider endpoint the app calls |
| `me endpoints` | 10 | Profile, preferences, tokens |
| `booking endpoints` | 8 | Booking lifecycle calls |
| `auth endpoints` | 7 | Login, register, logout |
| `product order endpoints` | 6 | Catalogue and orders |
| `destinationFor` | 6 | Deep-link routing |
| `review endpoints` | 5 | Reviews |
| `payment endpoints` | 4 | Order create and verify |
| `BOOKING_STATUS_LABELS` | 1 | Status naming |

`tests/components.test.tsx` (37)

| Suite | Tests | Covers |
|---|---:|---|
| `auth store` | 9 | Session store |
| `Field` | 8 | Form field |
| `query client` | 6 | Cache behaviour |
| `Button` | 5 | Button states |
| `SettingsList` | 3 | Settings rows |
| `FormError` | 2 | Error display |
| `Stat` | 2 | Stat tile |
| `Badge` | 1 | Badge |
| `EmptyState` | 1 | Empty state |

`tests/money.test.ts` (26)

| Suite | Tests | Covers |
|---|---:|---|
| `paymentSummary` | 5 | Payment summary wording |
| `cancellationNote` | 5 | Cancellation copy |
| `formatPaise` | 3 | Money formatting |
| `deadlineSummary` | 2 | Cancellation deadline |
| `ledger lines` | 2 | Provider ledger |
| `staff` | 2 | Staff display |
| `a held slot` | 2 | Waitlist hold |
| `moving an appointment` | 2 | Reschedule copy |
| `a saved shop` | 2 | Saved shop |
| `retrying a write` | 1 | Retry wording |

`tests/api-client.test.ts` (23)

| Suite | Tests | Covers |
|---|---:|---|
| `request` | 12 | Method, headers, body, auth |
| `ApiError` | 4 | Error shapes |
| `buildUrlForTest` | 3 | URL construction |
| `errorMessage` | 3 | User-facing messages |
| `base url` | 1 | Base URL |

`tests/logic.test.ts` (22)

| Suite | Tests | Covers |
|---|---:|---|
| `destinationFor` | 7 | Deep-link routing |
| `notification preferences` | 6 | Preference toggles |
| `formatRelative` | 4 | Relative time |
| `cn` | 3 | Class name helper |
| `BOOKING_STATUS_LABELS` | 1 | Status naming |
| `formatWhen` | 1 | Date formatting |

---

# Part 4 — Live verification (needs credentials)

The automated suites **block real network access** — `tests/conftest.py` raises
on any socket to a non-local host — so every external integration below is
mocked. These are the cases that have to be run for real once credentials exist.

**Environment variables required**

| Variable | Integration |
|---|---|
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | Payments |
| `WHATSAPP_PROVIDER`, `WHATSAPP_ACCOUNT_SID`, `WHATSAPP_AUTH_TOKEN`, `WHATSAPP_FROM`, `WHATSAPP_WEBHOOK_SECRET`, `WHATSAPP_TEMPLATE_ID` (MSG91) | WhatsApp |
| `PUSH_NOTIFICATION_URL` | Push notifications |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | Email |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Background jobs (Redis) |
| `AI_ENDPOINT`, `AI_API_KEY`, `AI_MODEL` | Suggestions and review summaries |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT` | Error tracking |
| `POSTGRES_DB`, `TEST_POSTGRES_DB`, `SECRET_KEY`, `FIELD_ENCRYPTION_KEY` | Database |

## L1 — Payments (Razorpay)

| ID | Case | Expected |
|---|---|---|
| L1.1 | Create an order for a booking with a deposit | Razorpay order id returned and stored against the booking |
| L1.2 | Pay through the Razorpay SDK | Payment captured; booking moves to confirmed |
| L1.3 | Deposit only, balance collected at the end | Both charges succeed; ledger matches |
| L1.4 | Abandon payment, then retry | No double booking, no orphan payment |
| L1.5 | Send the real `payment.captured` webhook | Signature verifies; booking updated once |
| L1.6 | Replay the same webhook | Idempotent — no second update |
| L1.7 | Send a webhook with a bad signature | Rejected, logged, booking untouched |
| L1.8 | Send `payment.failed` | Booking returns to a payable state, not confirmed |
| L1.9 | Tip after a completed appointment | Captured separately; provider keeps all of it |
| L1.10 | Refund after cancellation | Refund reaches the gateway with the right amount |

## L2 — WhatsApp

| ID | Case | Expected |
|---|---|---|
| L2.1 | Book an appointment | Exactly one confirmation with a working manage link |
| L2.2 | Provider has no WhatsApp number | Silent no-op, no error surfaced to the customer |
| L2.3 | Reply "cancel" | Booking cancelled, same rules as the app |
| L2.4 | Reply "reschedule" | Reschedule link sent |
| L2.5 | Reply "yes" | Confirmed |
| L2.6 | Reply with an unrelated message | Booked slot untouched |
| L2.7 | Send a webhook with a wrong shared secret | Rejected |
| L2.8 | Provider reports a delivery failure | Status reconciled; failure recorded |
| L2.9 | Booking cancelled, message sends | Message not sent |

## L3 — Push notifications

| ID | Case | Expected |
|---|---|---|
| L3.1 | Daily reminder to a customer with a live token | Push arrives |
| L3.2 | Reminder with a stale token | Failure recorded, token flagged for deactivation |
| L3.3 | Reminder with no token | Skipped as `skipped_no_token`, not counted as sent |
| L3.4 | Provider notification on a new booking | Push arrives |
| L3.5 | Check `/api/v1/observability/metrics/` | `reminder_delivery` counts are non-zero and correct |
| L3.6 | Point `PUSH_NOTIFICATION_URL` at a failing endpoint | `sent` falls, `failed` rises, alert raises after 20 attempts |
| L3.7 | Restore the endpoint | Alert resolves |

## L4 — Email

| ID | Case | Expected |
|---|---|---|
| L4.1 | Booking confirmation | Email sent, correct reference and manage link |
| L4.2 | Email verification | Code delivered; the code works |
| L4.3 | Password reset | Reset email delivered |
| L4.4 | Request a CSV export | Export email arrives with a working link |
| L4.5 | Open the export link twice | Both work; link does not break the booking |
| L4.6 | Use a wrong SMTP host | Failure is logged, no unhandled exception |

## L5 — Background jobs (Celery + Redis)

| ID | Case | Expected |
|---|---|---|
| L5.1 | Start worker and beat | Both connect; no `.delay()` fallback to an unconfigured app |
| L5.2 | Beat fires `send_daily_reminders` | Reminders go out once per booking |
| L5.3 | Beat fires `expire_stale_bookings` | Past bookings become `no_show` |
| L5.4 | Beat fires `check_delivery_health` | Alert raised or not, per the ratio |
| L5.5 | Materialise a recurring series | Next occurrence created on schedule |
| L5.6 | Re-booking nudge task | Sends only to lapsed customers who opted in |
| L5.7 | Kill the worker mid-task, restart | No duplicate sends; idempotent tasks only |

## L6 — Suggestions and summaries (AI)

| ID | Case | Expected |
|---|---|---|
| L6.1 | Suggest services for a query | Relevant suggestions returned |
| L6.2 | Provider with enough reviews | Summary generated and stored |
| L6.3 | Provider with too few reviews | No summary claimed; nothing misleading stored |
| L6.4 | AI endpoint returns garbage or times out | Keyword fallback used; request still succeeds |
| L6.5 | Model returns prose instead of the array | Parsed safely, not crashed on |

## L7 — Observability against a real deployment

| ID | Case | Expected |
|---|---|---|
| L7.1 | Make any request | `X-Request-ID` returned |
| L7.2 | Send a request through a gateway with `X-Request-ID` | That id is propagated |
| L7.3 | Trigger a real 500 | JSON log line with the same id; Sentry event tagged with it |
| L7.4 | Search Sentry by that request id | The event is found (the P5.5 acceptance criterion, live) |
| L7.5 | Run with no `SENTRY_DSN` | Error still findable by id in the logs |
| L7.6 | Call `/api/v1/observability/metrics/` | Real request rate, latency percentiles, conversion, no-show rate |
| L7.7 | Unauthenticated call to `/metrics/` | Rejected |

## L8 — End-to-end on a device or emulator

| ID | Case | Expected |
|---|---|---|
| L8.1 | Register → verify → book → pay → receive reminders | The whole journey completes |
| L8.2 | Book with a consultation form | Questions asked, provider sees the answers |
| L8.3 | Book a recurring series | Further visits appear on the calendar |
| L8.4 | Complete an appointment, then tip | Tip recorded, provider sees it |
| L8.5 | Write a review with a photo | Photo renders on the public shop page |
| L8.6 | Redeem a promo code and points | Both applied; totals match the quote |
| L8.7 | Deep-link into a notification | Correct screen opens |
| L8.8 | Kill the app mid-booking | No orphaned hold |

---

# Known gaps

Stated plainly rather than left to be discovered:

- **Every external integration is mocked.** The suites cannot pass a real socket,
  so L1–L8 above are genuinely unverified until credentials exist.
- **Celery runs eagerly in tests** (`config/settings/test.py`). Task *logic* is
  covered; broker behaviour, retries across restarts and beat scheduling are not.
- **No end-to-end browser test.** The web suite is unit-level. The CI serving
  check proves the built site serves and the SPA fallback works, but no test
  clicks through the shop list.
- **Email is never actually delivered.** Content and link generation are tested;
  deliverability and spam-folder behaviour are not.
- **No load or concurrency testing.** `test_performance.py` asserts query counts
  stay bounded, which is not the same as the site holding up under load.
- **`apps/web` has no linter.** The marketing site is unlinted while the mobile
  app is. Typecheck and tests still run.
