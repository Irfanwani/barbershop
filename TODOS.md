# TODOS

Thirty features, in the order they should be built.

## How this list was made

Two inputs, and the disagreement between them is the point.

**Market research.** I read 2026 comparisons of Fresha, Booksy, Vagaro,
Boulevard, Phorest, StyleSeat, GlossGenius, Square, Mangomint and Zenoti, plus
the product pages of the no-show specialists (NoSho, YepShow, SchedulingKit,
Chronos). One feature dominates every one of them:

> "A no-show on a 3-hour balayage empties a chair for the whole afternoon."
> — SchedulingKit

> "Deposits typically protect around 90% of lost income." — NoSho

> "Deposits, card on file and tap to pay... Cancel < 24h: forfeit 50% deposit.
> No-show: charge full service fee. Shown at booking. Clients agree before
> checkout." — Chronos

Deposits and the policy that makes them enforceable are the single most
requested feature in this category and we do not have either.

**A code audit.** Every YES/NO below was checked against the source, not
guessed. That found two real bugs (P0.1, P0.2) and killed several plausible
ideas that turned out to already exist — auth, password reset, email
verification, reminders, the booking lifecycle, the quote endpoint, rate
limiting. Planning any of those would have been waste.

Where the two disagreed, the code won. Where the code was silent and the
market was unanimous, that is what filled this list.

## Ground rules

Every feature below ships with:

- **Tests that would fail without it.** Not a coverage bump — a test asserting
  the behaviour, written before the implementation where that is honest.
- **Server-side authority.** Prices, fees, eligibility and balances are decided
  on the server. The client never computes them. See
  [0003](docs/decisions/0003-server-authoritative-pricing.md).
- **A migration if it adds a model**, with a reversible `RunPython`.
- **A regenerated OpenAPI schema** — the contract test will fail otherwise.
- **ruff + mypy clean**, because CI enforces both.
- **Its own commit and push.** One feature, one commit.

---

# P0 — Bugs

These are not features. They are things that are broken now.

## P0.1 The marketing site's shop list is broken

**Status:** done

`apps/web/app.js:63` called `GET /providers/` with no token, but
`ProviderListView` was `permission_classes = [IsAuthenticated]`. The section
silently rendered "Shops are not loading" in production. The price bands were
already `AllowAny` and worked fine, which is why it was never noticed — the
page looked alive.

Shop search, prices, the service index, categories and product browsing are now
`AllowAny`. Provider *detail* and availability stay authenticated: those are
per-customer reasoning about somebody's calendar, not a listing.

Anonymous search is rate limited to 60/min, tighter than any signed-in
endpoint, because it will happily page through every shop on the platform for
someone who has not signed up.

`tests/test_public_surface.py` is the regression — 14 tests covering which
endpoints work with no token and, just as importantly, which must not. Checked
against a reverted fix: five of them fail without it.

## P0.2 The marketing site advertises a feature that does not exist

**Status:** the claim is being made true

`apps/web/index.html` said the app has "saved shops". It does not. It is
being built as [P2.4](#p24-saved-shops) rather than deleted from the copy,
because saved shops are the cheapest retention feature available and the
backbone of the rebooking work in [P3.2](#p32-rebooking-nudges-for-lapsed-customers).

---

# P1 — Revenue protection

The research is unanimous that this is where the money is.

## P1.1 Deposits on long services

**Status:** done

Require a partial payment at booking, the balance on arrival. `Payment` is
1:1 with `Booking` today, so a second partial charge cannot even be stored —
this changes that relationship first.

- `deposit_percent` per service (Chronos/SchedulingKit both do percentage;
  half-deposits on anything over an hour is the industry default)
- `Payment` becomes 1:N with a `kind` of `deposit` or `balance`
- `Booking` carries `amount_paid` and `amount_due`
- Quote endpoint returns both, so the customer agrees before paying
- Expired deposits release, they do not silently convert

`Service.deposit_percent`; `Payment` is now one-to-many with a `kind` of
deposit, balance or full; `Booking` carries a frozen `deposit` and `balance`;
the quote returns both so the customer agrees before paying.

The strictest deposit across a basket wins — a customer booking a colour
service and a trim has agreed to the colour service's policy, and averaging
would under-charge the shop on the thing that costs it the chair time.

**Acceptance:** a ₹3,030 total with a 30% deposit quotes ₹909 + ₹2,121, and
`deposit + balance == total` for every total and percentage. Covered by 36
tests, including the property loop that checks the split for 123,457 × 101
combinations.

Writing them found three bugs in the first implementation: an unpaid deposit
reported as already settled, so the first charge asked for nothing; a balance
charge billed the deposit twice because it was not in `paid` yet; and `is_paid`
checked a frozen snapshot field, so nothing on a deposit booking could ever be
paid.

**Complete.** `POST /bookings/{ref}/collect/` records what was taken in the
shop — cash, UPI or card — and deliberately does not complete the booking.
Both sides of the app show the split: the checkout sheet says how much is due
now and how much at the shop, the booking detail shows what has been paid, and
the provider's booking list has a "Take ₹X" button.

Two blockers had to be cleared for it to work at all: the payment endpoint only
accepted `PENDING_PAYMENT`, so the moment a deposit moved a booking to
`CONFIRMED` the balance became unpayable; and the per-kind unique constraint
blocked a customer who abandoned checkout and came back.

What is still missing is what happens to the money when a booking is
cancelled — that is [P1.3](#p13-refunds).

## P1.2 Cancellation policy with a deadline and a late-cancel fee

**Status:** done

Today `can_be_cancelled` checks status only. Anything can be cancelled at any
moment, which means a slot can be freed 30 seconds before it starts.

- Per-shop `cancellation_window_hours` (default 24)
- Per-shop `late_cancel_fee_percent` (default 0)
- The deadline and the fee are **shown at booking**, in the quote and the
  checkout screen — never applied retroactively
- Provider-initiated cancellation is always fee-free; the fault is theirs
- `Booking` records the policy that applied, so a later change to the shop's
  policy cannot alter an old booking

**Done.** `cancellation_window_hours` and `late_cancel_fee_percent` on the
shop, frozen onto every booking, with `late_cancel_fee` computed at booking
time from the deposit.

A late cancellation **succeeds** and forfeits the agreed slice. The only
refusal is a booking that cannot be cancelled at all — refusing a late
cancellation would just leave the shop with a slot nobody is coming to.

The fee is a slice of the **deposit**, not the total, and is a one-directional
penalty: a provider cancelling is always free. They still have the chair and
the customer is not at fault.

Zero is meaningful in both fields and means opposite things: a zero window is
"no free window, any cancellation forfeits", and a zero fee is "always
refunded". Both directions are reachable without a second setting.

22 tests, including that tightening the shop's window or fee does not reach a
booking made before the change.

**Not yet:** the forfeited money is recorded but not moved. That is
[P1.3](#p13-refunds).

## P1.3 Refunds

**Status:** done

The scaffolding is complete and inert: `PaymentStatus.REFUNDED`,
`Payment.refunded_at`, `Payment.refund_id` and `BookingStatus.REFUNDED` all
exist and nothing ever writes them. So a cancelled-and-paid booking has no
way to give the money back except an out-of-band manual one.

- Provider-triggered refund on a paid booking, full or partial
- Razorpay refund call, with the refund id recorded
- Webhook reconciliation, since a refund is asynchronous
- Refunds blocked once a booking is `completed` — the service was had

**Done.** `payments/refunds.py` with partial refunds, a running
`refunded_amount`, and webhook reconciliation.

Cancelling now moves the money in the same request: the deposit is refunded to
the amount the frozen policy promised, and when a late cancellation forfeits the
whole deposit the balance is refunded instead, because that is where the money
the customer wants back actually is.

A gateway outage does not undo the cancellation — the booking is cancelled
either way, and the response says the refund could not be started rather than
letting a slow Razorpay look like a cancellation that did not happen.

**Acceptance:** a refund can never exceed what was taken (a shop must not be
able to mint money out of a cancellation); a completed appointment cannot be
refunded silently; cash is settled without asking the gateway; partial refunds
accumulate and leave the payment captured while money is still owed.

27 tests, including the two that protect the shop's money.

## P1.4 Provider payout ledger and withdrawal

**Status:** done

The most serious gap in the whole codebase. A provider can save bank details
and they are registered with Razorpay, and then... there is no balance, no
ledger, no settlement and no way to withdraw. The supply side of the
marketplace cannot get paid through the product at all.

- `LedgerEntry` — every amount a provider earns or is paid, append-only
- Balance derived from the ledger, never stored and updated in place
- A settlement run (Celery) that pays out cleared earnings to the bank account
- Withdrawal request + history in the provider app
- Refunds and chargebacks debit the ledger

**Done.** `LedgerEntry`, append-only and immutable, with the balance derived
from it rather than stored. `GET /providers/me/balance/`,
`GET /providers/me/ledger/`, `POST /providers/me/withdraw/`.

A completed booking credits two lines — the price and the platform's share
negatively — so a shop asking "why is this 19,800 not 20,000" has a row that
answers it. A cancellation or a no-show credits nothing; earnings are credited
on completion because a booking can still be refunded.

A withdrawal may never exceed the *cleared* balance: pending earnings are not
payable because the appointment has not happened yet. An unverified bank
account is refused whatever the balance. A gateway outage still moves the
balance, because the money has left ours either way and leaving it would let a
provider withdraw the same money twice.

**Thirty-one tests.** Writing them found three bugs in the first
implementation: the earning line recorded the fee amount so the two cancelled to
zero; a failed transfer added a positive line that doubled the balance; and the
payout entry was keyed by the gateway's transfer id rather than ours, so the
settlement callback could never find it.

The provider app has an **Earnings** tab: what is available to withdraw, what
is pending and why, and a statement where every line is explained in words —
"Appointment earned", "BarberShop fee", "Withdrawal". Enum values on a
statement are a support ticket.

---

# P2 — Marketplace quality

## P2.1 Individual staff members

**Status:** done

The single biggest structural gap. `employee_count` is an integer, so a shop
with four barbers is "capacity 4" and no booking ever names a barber. Every
competitor handles this, and it is the first thing a customer asks for:
"can I book with Ravi?"

- `Staff` model: profile, bio, photo, working hours, services, a share of the
  shop's capacity, and their own rating
- Bookings pick a staff member rather than a shop
- Availability becomes per-staff, and the shop's grid is the union
- A shop's `employee_count` becomes derived from its staff rows

**Done.** `Staff` with a name, bio, photo and their own weekly hours; capacity
derived from the active rows; bookings name a person; per-weekday hours
narrow their availability.

**Acceptance:** two barbers can hold simultaneous bookings; the customer can
choose between them; choosing one who is closed that day offers nothing —
all three tested.

**Deliberately not derived from `employee_count` any more.** Capacity is
`Staff.objects.filter(is_active=True).count()`, falling back to the old integer
only while a shop has named nobody. Two sources of truth for capacity is how
three simultaneous bookings become four.

**A data migration carries existing headcount over**, one placeholder row per
unit of `employee_count`. Without it, a shop with four barbers drops to capacity
one the moment it ships — a silent regression that no test would catch, because
the tests build their own providers.

**Retired, never deleted.** A booking made in March still names the person who
did it in July. `DELETE` sets `is_active=False`; `PROTECT` on the FK makes a
hard delete impossible by accident.

Writing the tests found five bugs:

- **A new staff member was created inactive.** A multipart form cannot express
  an absent checkbox and DRF turns "absent" into `False`, so a provider posting
  a plain form got someone who was silently unbookable. `is_active` is now
  forced on create.
- **The public staff list was gated behind `IsProvider`** — customers, the
  people who need it, could not read it.
- **A staff member with no hours of their own was treated as closed** whenever
  the shop had set any, rather than following the shop.
- **Capacity reintroduced an N+1.** One `COUNT` per provider on the search page,
  which is the exact regression that once turned a 20-row page into 1,600
  queries. It needed a `Coalesce` around the subquery: a subquery with no
  matching rows returns NULL, not 0, and `headcount()` cannot tell "not
  annotated" from "annotated as null".
- **The provider's staff list paginated and the public one did not**, so the
  same data had two shapes for the client to handle.

**In the app.** A provider adds and retires people from a **Team** tab, which
states plainly that the list *is* their capacity — a provider who does not
realise that will assume it is decorative. Rows the migration created are
flagged as unnamed until someone gives them a real one.

A customer picks a barber in the booking sheet, alongside the time. The default
is Anyone, which is the old behaviour exactly: a shop that has named nobody
has no chips and nothing changes for them. Someone who does not work the day
being booked is not offered at all, rather than offered and refused at the
server.
rather than silently falling back to the shop.

## P2.2 Waitlist, with automatic fill on cancellation

**Status:** todo

When a slot frees, it sits empty. The entire niche is built on this —
"as soon as you add new availability, your waitlist gets notified instantly"
(NoSho), "first to reply gets the slot — filled in seconds" (YepShow).

- `WaitlistEntry`: customer, shop, staff, service, preferred windows, created
- On cancellation, offer the freed slot to matching entries, first come first
  served, with a hold window before it goes public
- Push notification to the offered customer
- Declining or letting the hold expire releases it to the next in line

**Acceptance:** cancelling a booked slot notifies the first matching waitlist
entry; if they decline, the next is offered; the slot returns to public after
the hold expires.

## P2.3 Rescheduling

**Status:** todo

Changing a booking today means cancelling and rebooking, which loses the
reference, the reminders and the review link, and can double-charge.

- Move a booking to a new slot, preserving its reference and payment
- Re-check availability and working hours under the new time
- Re-verify the price — the service may have changed price since
- The cancellation policy applies to rescheduling too, otherwise it is a
  loophole around late-cancel fees

**Acceptance:** rescheduling keeps the same reference; rescheduling onto a
booked slot is refused; rescheduling inside the late-cancel window is
treated as a cancel and a new booking.

## P2.4 Saved shops

**Status:** todo

The marketing site currently promises this. It is also the cheapest possible
retention feature and the backbone of the rebooking and lapsed-customer work
in P2.7.

- `SavedShop`: customer, provider, optional note ("my usual place")
- Default saved shop used to pre-fill search origin
- "Book again" from a saved shop, with the shop's current prices
- Saved shops do not bypass `is_accepting_bookings` — a closed shop still
  shows, greyed

**Acceptance:** saving twice is idempotent; a customer sees saved shops
first on browse; a shop that stops taking bookings still appears in the list.

## P2.5 Public booking link per shop

**Status:** todo

Every single competitor has this and it is how independents actually get
customers — SchedulingKit: "Add your NoSho link to your bio, stories,
WhatsApps and emails." A shop owner sharing a link in an Instagram bio is the
main acquisition channel this category has.

- `GET /shops/{slug}/` — a server-rendered page, not an app deep link
- Shareable, works with no app installed
- Open Graph tags so it previews usefully when pasted into a chat
- The slug is the shop's own, and can be changed

**Acceptance:** a shop page renders with its services and prices; it links
into the app or a web checkout; changing the slug breaks the old URL cleanly.

---

# P3 — Retention

## P3.1 Loyalty points

**Status:** todo

Present in every competitor (Boulevard's is "advanced", StyleSeat's is
"basic", KwickStudio's is 5-tier). We have none.

- Points per booking, configured per shop
- A balance on the customer account
- Redemption capped so it can never exceed the booking total
- Points expire, or they quietly become a liability on the books

**Acceptance:** completing a booking credits points; a redemption cannot make
a total negative; a points balance survives the provider being deleted from
the marketplace.

## P3.2 Rebooking nudges for lapsed customers

**Status:** todo

"Most salon owners have no idea how many clients rebook within 6 to 8 weeks"
(SchedulingKit). Neither do we, and this is the cheapest revenue on the
platform: the customer already liked the haircut.

- A Celery job finding customers whose last completed booking was 5–8 weeks ago
- Push, sent once per customer per shop, respecting notification preferences
- The message contains a booking link, not a marketing blast

**Acceptance:** a customer 7 weeks past their last booking is nudged exactly
once; a customer with reminders off is not.

## P3.3 Recurring bookings

**Status:** todo

"Trims every 4 weeks, so their next visits are already on the calendar"
(SchedulingKit).

- A customer books a series at an interval
- Celery materialises the next occurrence, skipping rather than double-booking
- The customer can stop the series
- Each occurrence is an independent booking — it can be cancelled or rescheduled
  on its own, which matters because they are separately chargeable

**Acceptance:** a six-week series produces the next booking at six weeks, not
at seven; skipping one occurrence does not shift the rest.

## P3.4 Referral programme

**Status:** todo

Give a credit, get a credit. Standard in the category, absent here.

- A referral code per customer
- A one-time credit to both sides on the referred customer's first completed
  booking
- Self-referral and same-account abuse are rejected
- Referrals are attributed to the shop, so a provider can see what worked

**Acceptance:** a self-referral credits nobody; a referral credits once, on
completion, not on booking.

## P3.5 Push preferences synced to the server

**Status:** todo

A real inconsistency today: the mobile app keeps notification preferences in
AsyncStorage, while the backend already has `reminders_enabled` and
`marketing_enabled` on both profiles. The user switches reminders off on one
phone and keeps getting them on the other, which is exactly the complaint that
motivated the single-app rebuild.

- `GET/PUT /me/notification-preferences/`
- The device store becomes a cache of the server's answer, not the truth
- Reminder tasks already read the profile; this makes the app agree with them

**Acceptance:** switching off on one device changes the other on next fetch;
the reminder task and the settings screen cannot disagree.

## P3.6 Two-way WhatsApp confirmations

**Status:** todo

Push fails silently — the app is closed, the token is stale, the notification
is muted. India runs on WhatsApp: "Email and WhatsApp reminders sent before
every booking" is NoSho's headline feature.

- WhatsApp provider (MSG91 / Twilio / GXT)
- Confirmation with a link, and yes/reschedule/cancel replies
- Delivery status reconciled back by webhook
- Charged per message, so send-once and idempotent

**Acceptance:** a booking sends one confirmation; a webhook retry does not send
a second; a reply that says "cancel" cancels the booking.

---

# P4 — Provider tools

## P4.1 Server-side provider analytics

**Status:** todo

The provider dashboard computes three numbers **on the device** from the
bookings list. That is wrong three ways: it is wrong if you page beyond the
first page, wrong if the device is offline, and it cannot show anything about
periods you have to page backwards through.

- Revenue, bookings, no-show rate, rebooking rate, utilisation, per service
- Over a period, compared with the previous one
- Computed in SQL, paged properly, no client arithmetic

**Acceptance:** the numbers match what the bookings list contains across
*every* page, not the first.

## P4.2 Client notes and consultation forms

**Status:** todo

The provider sees `Booking.notes` — a 500-character free-text box the
customer fills in at booking. Everything a barber actually needs to know
before a client sits down is missing.

- Provider-authored consultation forms attached to a service
- Customer answers at booking; the provider sees answers on the booking
- Sensitive answers flagged so they are shown only to that provider

**Acceptance:** a form attached to "Colour service" is answered at booking
and visible on the provider's booking detail.

## P4.3 Tips

**Status:** todo

Universal in this category, absent here. Complicated by our fee model — a tip
is not part of the booking total, so it must not touch the platform fee.

- Customer adds a tip at the end of a completed booking
- Paid through Razorpay separately from the booking
- Provider sees per-barber tips, and they are excluded from the fee

**Acceptance:** a tip is paid once, recorded against the staff member, and
never counted as platform revenue.

## P4.4 Promo and discount codes

**Status:** todo

- Percentage or fixed amount, with an expiry and a usage cap
- Scoped to a shop, a service, or the platform
- Applied server-side at quote time; the client sends only the code
- The fee is calculated on the discounted amount, and that is stated plainly

**Acceptance:** an expired code is refused at quote and at checkout; the
discount reduces the fee base and the customer is shown that.

## P4.5 Review reminders and photo reviews

**Status:** todo

Reviews exist and are tied to completed bookings, so the trust signal is
already right. Nobody is being asked for one.

- A Celery nudge after a completed booking
- Photo upload on a review
- Reply already exists; notify the provider when one arrives
- A provider can request removal only for abuse, not for being rated badly

**Acceptance:** a completed booking is nudged once; a review with a photo
renders on the shop page.

---

# P5 — Platform

## P5.1 Idempotency keys on payment endpoints

**Status:** todo

`capture()` is internally idempotent for webhook retries, but a client
retrying `POST /payments/verify/` on a flaky connection is not protected. The
mobile app explicitly disables mutation retries as "not idempotent" — this is
the fix that would let it turn them back on.

- `Idempotency-Key` header, stored with the request fingerprint
- A repeat with the same key returns the first response
- A repeat with the same key and a *different* body is a 409

**Acceptance:** two identical verify calls create one capture; the same key
with a different body is rejected.

## P5.2 API keys for third parties

**Status:** todo

Only session/token auth exists. A POS integration or an owner's dashboard
cannot talk to this API without impersonating a user, so the platform cannot be
embedded anywhere.

- Scoped keys per integrator, hashed at rest
- Scopes matching the read/write split
- Rate limits per key, and usage visible to the key's owner

**Acceptance:** a key with read scope cannot write; a revoked key stops
working immediately.

## P5.3 Abuse and no-show scoring

**Status:** todo

NoSho sells "no-show intelligence": track repeat offenders, auto-flag risky
clients, suggest deposits based on history. We have a `no_show` status and
nothing that learns from it.

- Per-customer no-show rate, from completed and no-show bookings
- The booking quote suggests a deposit for a customer with a poor record
- A provider can require a deposit outright
- Abusive behaviour (mass booking/cancelling) is flagged

**Acceptance:** a customer with two no-shows in five bookings is recommended
a deposit, and the recommendation is advisory, not enforced.

## P5.4 Provider CSV export

**Status:** todo

Every salon runs on a spreadsheet. If their data cannot leave our product
they will maintain two records, and ours will be the stale one.

- Bookings, revenue and clients as CSV
- Generated by a Celery job and emailed, because a year of bookings is not a
  synchronous response
- Payout history alongside

**Acceptance:** an export contains every booking in the period, not just the
first page.

## P5.5 Observability

**Status:** todo

`logger.exception` in six places and no idea whether any of them fire in
production.

- Structured JSON logs with a request id
- Error tracking with the request id attached
- Metrics: request rate, latency percentiles, booking conversion, no-show rate,
  reminder delivery
- An alert when reminder delivery starts failing — the silent failure mode of
  a Celery app

**Acceptance:** a failed request is findable by its request id in the error
tracker.

## P5.6 Timezone correctness

**Status:** todo

Shop hours are naive `TimeField`s and the Celery beat runs on UTC. Works for a
single-country marketplace and silently corrupts once it is not one. The
customer profile already carries `timezone_name`; the shop does not.

- A timezone on the shop, defaulting from the account
- Working hours interpreted in the shop's timezone
- Reminder lead times computed in local time, so a 3-hour lead before a 09:00
  appointment is 06:00 local and not 06:00 UTC

**Acceptance:** a shop in a non-UTC timezone gets its reminders at the right
local hour.

---

# Order of work

P0 first because they are broken. Then P1, because that is where the research
says the money is and where the marketplace is currently weakest — a platform
that cannot collect a deposit, cannot refund, and cannot pay a provider out is
not yet a marketplace.

P2 next, because structural gaps (staff, waitlist, reschedule) get more
expensive the longer they are left — every booking made before staff exist has
to be migrated.

P3 and P4 after, once the money works. P5 when there is enough traffic for the
absence of observability to hurt.

## Deliberately not doing

- **A conversational booking assistant.** Booking is five taps. Research on
  AI features in this category found the same thing we wrote in
  [0005](docs/decisions/0005-what-ai-is-for.md): the assistants that exist are
  sold as receptionists, not as booking flows, and a chatbot cannot say "I have
  cancelled BK-7QK4M2" with the confidence a button can.
- **Multi-location.** Real, and genuinely a large piece of work, but every shop
  today has exactly one profile and none have asked. Revisit when one does.
- **Native POS hardware integration.** Razorpay handles the card side.

## Knowledge base page

**Status:** done

A searchable documentation page at `/knowledge`, covering the whole product for
both audiences: booking and paying, deposits and the balance, cancellation and
refund policy, products, and — for providers — working hours, taking payments,
earnings, the 1% fee and withdrawals.

Written as data rather than markup, and asserted rather than assumed: every
entry has an id so anchors link, ids are unique, and an answer describing
something unshipped has to say so. That last check exists because a
knowledge base that documents the roadmap in the present tense is worse than
having none. Rescheduling is the one thing it has to decline.

Search matches on what people type rather than what the docs say — "money
back" finds "How do refunds work?", "did not turn up" finds the no-show fee.
