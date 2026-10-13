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

**Status:** done

`apps/web` said the app has "saved shops". It did not. It is now built as
[P2.4](#p24-saved-shops) rather than deleted from the copy, because saved
shops are the cheapest retention feature available and the backbone of the
rebooking work in [P3.2](#p32-rebooking-nudges-for-lapsed-customers).

Building it turned up a live bug nobody had looked for: `is_accepting_bookings`
was never in the public search response, so **every shop on the marketing site
had been rendering as "Not taking bookings"** since launch.

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

**Status:** done (two accounting bugs found and fixed after shipping — see
below)

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

**Status:** done

When a slot frees, it sits empty. The entire niche is built on this —
"as soon as you add new availability, your waitlist gets notified instantly"
(NoSho), "first to reply gets the slot — filled in seconds" (YepShow).

- `WaitlistEntry`: customer, shop, staff, service, preferred windows, created
- On cancellation, offer the freed slot to matching entries, first come first
  served, with a hold window before it goes public
- Push notification to the offered customer
- Declining or letting the hold expire releases it to the next in line

**Two bugs, found after this shipped and since fixed.** Both are the kind
that do not fail loudly: the code ran, the refund succeeded, the tests
passed.

- **A refunded payment still counted as paid.** `amount_paid` summed captured
  payments without subtracting `refunded_amount`, so a *partial* refund left
  the booking reading as fully paid and `amount_due` at zero while the money
  had already gone back. The customer looked paid up and the shop saw no
  balance due. `amount_paid` is now net of refunds.
- **A refunded deposit still counted as held**, so `requires_deposit` was
  false on a booking whose deposit had been handed straight back and the shop
  was never asked for it again.
- **The refund webhook was never handled.** `refund.processed` and
  `refund.failed` were acknowledged and dropped, so `reconcile` — written,
  tested, and wired to nothing — never ran. A refund initiated synchronously
  but settled by the gateway days later left the booking looking like money
  still owed. Both events are handled now, and the gateway is treated as the
  authority on what was actually refunded.

**Acceptance:** cancelling a booked slot notifies the first matching waitlist
entry; if they decline, the next is offered; the slot returns to public after
the hold expires — all three tested, 29 tests.

**A window, not a slot.** "Any time this week" is what most people mean, and
pinning one minute would mean the waitlist misses almost every cancellation —
the one thing it exists for. The window is checked against the freed booking's
own start and end, so someone who said "this afternoon" is not woken next
Tuesday.

**The hold is the feature.** `SlotHold` is consulted by `has_room`, so an
offered slot stops being publicly bookable for as long as the hold lasts.
Without it "first to reply gets the slot" is a lie: the seconds between the
offer and the reply belong to whoever is watching the list, not to the person
who was notified.

**One turn each.** An offer that lapses is not re-offered to the same person.
They already had their turn; expire, re-offer, expire, re-offer would leave the
people behind them watching an empty chair.

**A lapsed hold costs nothing if the cleanup task never runs.** Every
availability check treats an expired hold as no hold, so a dead Celery worker
costs delay for the next person in line and nothing else.

**Accepting re-runs the full booking rules** rather than trusting the offer. An
entry can sit for days across a price change or a revised cancellation policy,
and a booking built from stale assumptions is worse than a refused accept.

**In the app.** A customer joins from the booking sheet when nothing is free,
and answers offers on a **Waitlist** tab. An offer shows the shop, the
service, the time and the deadline it is held until — yours without a
deadline is how somebody ends up being woken by another person taking their
slot. A lapsed offer says it has run out and that the slot may already be
gone, rather than offering a button that will fail.

Writing the tests found three bugs:

- **Accepting an offer was refused by its own hold.** The hold stopped the
  customer it was held *for* from booking it. Released first now; both happen
  in one transaction so nothing slips in between.
- **A lapsed waiter was re-offered the same slot forever**, so the queue behind
  them never moved.
- **A free-text `{action}` URL segment** accepted any verb. Two explicit routes.

## P2.3 Rescheduling

**Status:** done

Changing a booking today means cancelling and rebooking, which loses the
reference, the reminders and the review link, and can double-charge.

- Move a booking to a new slot, preserving its reference and payment
- Re-check availability and working hours under the new time
- Re-verify the price — the service may have changed price since
- The cancellation policy applies to rescheduling too, otherwise it is a
  loophole around late-cancel fees

**Acceptance:** rescheduling keeps the same reference; rescheduling onto a
booked slot is refused; rescheduling inside the late-cancel window is
treated as a cancel and a new booking — all three tested, 21 tests.

**The same booking throughout.** Same reference, same payments, same frozen
items. Cancelling and rebooking would lose the reference the customer has
been quoting, drop the reminders, break the review link, and on a booking
with a deposit paid could refund it once and then charge it again.

**The price is re-checked, and a change stops the move.** Silently charging
the new one is a bait and switch; silently charging the old one is a shop
eating a cost it agreed nowhere. Both figures come back with a 409 and the
move happens only once someone sends `accept_price_change`.

**A service the shop has since dropped blocks the move** rather than being
quietly removed from it. Arriving for something nobody does any more is a
worse outcome than being told.

**The deposit split moves with the price.** It is a percentage of the total;
holding the old figure while the total changes is the kind of thing that
only surfaces in a reconciliation three months later.

**Inside the cancellation window this cancels instead of moving**, and says
so. A reschedule button that silently dodges the late-cancel fee is a way to
never pay one. The provider moving their own appointment late is still free —
the fee only ever punishes the customer.

**In the app.** "Change the time" sits next to "Cancel booking" on the
booking screen, because they are the two answers to the same question and
finding one without the other is the problem. All three outcomes are shown:
it moved; the price changed, with both totals and agreeing as a separate
tap; or it fell inside the window and became a cancellation, with the fee
that was charged named.

## P2.4 Saved shops

**Status:** done

The marketing site currently promises this. It is also the cheapest possible
retention feature and the backbone of the rebooking and lapsed-customer work
in P2.7.

- `SavedShop`: customer, provider, optional note ("my usual place")
- Default saved shop used to pre-fill search origin
- "Book again" from a saved shop, with the shop's current prices
- Saved shops do not bypass `is_accepting_bookings` — a closed shop still
  shows, greyed

**Acceptance:** saving twice is idempotent; a customer sees saved shops
first on browse; a shop that stops taking bookings still appears in the list —
all three tested, 17 tests.

**A paused shop stays saved.** Somebody's usual barber does not stop existing
because they took a holiday. It shows greyed with its current price, and
saving it does not bypass the pause — a bookmark is not a way round a closed
shop.

**Browse puts saved shops first**, before the shops nearest to wherever the
customer happens to be standing.

**A live bug found on the way.** `is_accepting_bookings` was never in the
public search response, so every shop on the marketing site rendered as "Not
taking bookings" with no price. The website code read it correctly; the field
simply was not sent. Found by writing a test about what a client depends on,
which is the only thing that catches this class of bug — the code looks fine.

**In the app.** A **Saved** tab, and a Save button on the shop page. A paused
shop stays in the list, greyed, with "Not taking bookings at the moment" in
place of the price — hiding it would make a saved list look broken at exactly
the moment somebody wants it. Prices shown are the shop's current ones.

## P2.5 Public booking link per shop

**Status:** done

Every single competitor has this and it is how independents actually get
customers — SchedulingKit: "Add your NoSho link to your bio, stories,
WhatsApps and emails." A shop owner sharing a link in an Instagram bio is the
main acquisition channel this category has.

- `GET /shops/{slug}/` — a server-rendered page, not an app deep link
- Shareable, works with no app installed
- Open Graph tags so it previews usefully when pasted into a chat
- The slug is the shop's own, and can be changed

**Acceptance:** a shop page renders with its services and prices; it links
into the app; changing the slug breaks the old URL cleanly — all tested.

**Server-rendered, at the root, with no JavaScript.** A link somebody is
excited about should not depend on a bundle arriving first. It is also what
makes the link preview work: Open Graph tags are read by the chat app before
anything runs.

**The slug is the shop's own and can be changed.** The link gets printed on
leaflets, so it has to be memorable enough to type.

**Changing it breaks the old URL, deliberately.** A redirect would keep every
printed leaflet working — and would also mean the shop can never start again
on a name it has outgrown, because the old one would shadow it for good.

**A three-step migration.** A unique index cannot be built while every row
still holds the same empty slug, which is exactly the state a plain `AddField`
leaves the table in. Add the column bare, fill it, then index it.

**A fourth trap in the same migration**: `SlugField` indexes itself by
default, so adding it bare and then adding the unique index creates the same
index twice. The first step is explicitly `db_index=False`.

14 new tests, 793 total.

---

# P3 — Retention

## P3.1 Loyalty points

**Status:** done

Present in every competitor (Boulevard's is "advanced", StyleSeat's is
"basic", KwickStudio's is 5-tier). We have none.

- Points per booking, configured per shop
- A balance on the customer account
- Redemption capped so it can never exceed the booking total
- Points expire, or they quietly become a liability on the books

**Acceptance:** completing a booking credits points; a redemption cannot make
a total negative; a points balance survives the provider being deleted from
the marketplace — tested, 23 tests.

**The balance is a sum over a ledger, oldest credit first against oldest
spend.** Not a flat sum: a flat sum says somebody has 100 points when 90 of
them expired last week and were already spent, and a customer whose points
vanish is a customer who stops trusting the number.

**Expiry needs no job that rewrites history.** Walking the queue means an
expired credit simply stops counting. I first wrote a cleanup task that zeroed
lapsed credits — which corrupts the ledger the moment one of them was already
spent, and puts two sources of truth on the books.

**The redemption cap is applied before the number is shown**, not only when it
is used, so what is on screen is what will be honoured. Points are capped as a
share of the booking total: uncapped, they are a way to give an appointment
away.

**Points are awarded on completion**, for the same reason earnings are — at
booking time they are points for appointments that get cancelled or never
happen.

**Spent at the quote, and the balance is shown with its expiry.** The app asks
the server what the points are worth rather than multiplying a rate itself, and
the same figure is sent into the booking request. `expiring_soon` is shown next
to the balance on purpose: a number that quietly shrinks between visits is a
number nobody trusts, and the warning is cheaper than the complaint.

**One award per booking, enforced by the database.** The completion endpoint
already guards on status; a second guard that cannot be forgotten is what
stops it being reintroduced.

**A balance survives the shop leaving the marketplace.** The points were
earned by the customer, not by the platform.

**Spendable at quote and at checkout**, on the same `redeem_points` field.
A quote records nothing — it happens on every tap of a slot and none of them
should move a balance — and the spend happens inside the booking's own
transaction, so points cannot be spent against an appointment that then fails
to save.

**A code comes off before points.** Otherwise the points cap is measured
against a number the customer has already been shown discounted, and the same
basket prices differently depending on which order the server happened to apply
them in.

**The cap is measured against the subtotal everywhere.** It was briefly
measured against items-plus-fee at redemption and items-alone at quote, which
meant the cap shown and the cap applied were different numbers.

**Still to do:** no app screen for spending them at checkout.

## P3.2 Rebooking nudges for lapsed customers

**Status:** done

"Most salon owners have no idea how many clients rebook within 6 to 8 weeks"
(SchedulingKit). Neither do we, and this is the cheapest revenue on the
platform: the customer already liked the haircut.

- A Celery job finding customers whose last completed booking was 5–8 weeks ago
- Push, sent once per customer per shop, respecting notification preferences
- The message contains a booking link, not a marketing blast

**Acceptance:** a customer 7 weeks past their last booking is nudged exactly
once; a customer with reminders off is not — tested.

**Grouped per customer, not per shop.** The question is "has this person
stopped coming back", not "has this person stopped coming back to *that*
shop". Somebody who moved to a competitor three shops over is not ours to
nudge back into this one, and telling them about a shop they have moved on
from is the fastest way to get a category muted.

**The window is 5 to 8 weeks, and the top end is a hard stop.** Somebody
mid-routine is not lapsed; nudging them is nagging. Past six months they are
gone rather than lapsed, and a message unsettles rather than helps.

**Once per customer per shop, ever, and the record of it is its own table.**
This cannot be derived from booking dates: a customer who rebooks and lapses a
second time looks exactly like one being nudged for the first time, and the
second message is the one that gets everything muted.

**Somebody who opted out is not nudged *and not recorded*.** Recording them
would mean opting out later would not stop a nudge that was already due.

**A link to the shop's page, not an offer.** They already know this shop.
What they have forgotten is that it exists — and the link is a web page, not a
deep link, because they may not have the app.

18 new tests, 835 total.

## P3.3 Recurring bookings

**Status:** done

"Trims every 4 weeks, so their next visits are already on the calendar"
(SchedulingKit).

- A customer books a series at an interval
- Celery materialises the next occurrence, skipping rather than double-booking
- The customer can stop the series
- Each occurrence is an independent booking — it can be cancelled or rescheduled
  on its own, which matters because they are separately chargeable

**Acceptance:** a six-week series produces the next booking at six weeks, not
at seven; skipping one occurrence does not shift the rest — tested, 28 API tests
and 7 app tests.

**Dates come from an origin, never from the last thing that happened.**
Occurrence *n* is always at `starts_at + n * interval`. This is the whole
design, and it is the part a naive implementation gets wrong: computing the next
booking as "the last one we managed, plus the interval" slides every later visit
a week earlier each time one is missed. A customer who skipped February would
find March sitting in February's slot, forever.

**A week that cannot be booked is stepped over, not retried.** The first version
kept trying the blocked week, which meant one taken slot stalled the entire
series behind it and the customer quietly stopped turning up. `next_index()`
skips occurrences whose moment has passed with nothing booked. Both acceptance
tests fail against the naive implementation — verified by mutating the model
and watching them go red.

**Only about three weeks of a series exist at once.** Each occurrence is
separately chargeable, so materialising a six-visit run on day one would leave a
shop's chair committed to five unpaid appointments. One occurrence per run, and
nothing beyond the booking horizon is ever created.

**Each occurrence is priced by the same function as a one-off booking.** The
money lives in `bookings/pricing.py` and both callers use it, because a series
whose third visit quietly costs something different from the first is the exact
bug having two implementations invites. Verified by running the booking,
deposit, promotion and loyalty suites through the refactor unchanged.

**The 90-day booking limit is applied where bookings are made, not where a
series is declared.** Six trims every four weeks spans five months; refusing to
even *record* that because the last visit is far out would refuse the feature.

**Stopping leaves the visits already booked alone.** They are separately
chargeable and may already be paid for, so a customer who booked six weeks of
trims is entitled to the two that have happened.

**The app sends an interval and a count, never a list of dates.** A client that
worked out the schedule itself would put two visits in the same week the first
time a phone disagreed about the length of a month.

## P3.4 Referral programme

**Status:** done

Give a credit, get a credit. Standard in the category, absent here.

- A referral code per customer
- A one-time credit to both sides on the referred customer's first completed
  booking
- Self-referral and same-account abuse are rejected
- Referrals are attributed to the shop, so a provider can see what worked

**Acceptance:** a self-referral credits nobody; a referral credits once, on
completion, not on booking — tested, 27 API tests and 8 app tests.

**A referral programme is a way to mint points**, so nearly every rule here is
about closing a hole rather than about generosity:

- **Self-referral is refused by the database**, not by a view. A check
  constraint, so no endpoint written in a hurry can forget it.
- **A customer has one referrer for life.** `referred` is unique. The second
  code they try is ignored - the booking still goes ahead, because somebody
  mistyping a code at checkout must not lose their slot.
- **The code waits for a completed booking.** Not the booking it was entered
  at: that can be cancelled, rescheduled into next month, or turn into a
  no-show, and a reward for an appointment that never happened is a purchase of
  points.
- **A cancellation lapses the referral rather than deleting it.** Deleting it
  would quietly hand the customer a second referrer after they lost nothing.

**The referral is linked to its booking the moment the code is used**, which is
what lets a cancellation find it and lapse it. The first version only set the
link when paying out, so a cancelled referral survived the appointment it was
attached to falling over - caught by a test, not by reading the code.

**Attribution goes to the shop that did the work**, not the shop that issued
the code. Somebody can hand out their code and send their friend somewhere else
entirely, and crediting the issuer would be a lie told in the ledger.

**Referral points are ordinary points**, written into the same append-only
ledger with an expiry. A credit written anywhere else would be points nobody
can explain, and one with no expiry is a liability the platform cannot plan
for.

**The code is made on first use, not at signup.** A code for somebody who never
refers anybody is a row nobody will ever read, and writing to a table on every
registration is a cost paid by everybody for the benefit of nobody.

**It has no confusable characters** - no zero/O, no one/I. Somebody is going to
read this out over the phone, and a code that does not survive being read aloud
is not a referral code.

## P3.5 Push preferences synced to the server

**Status:** done

A real inconsistency today: the mobile app keeps notification preferences in
AsyncStorage, while the backend already has `reminders_enabled` and
`marketing_enabled` on both profiles. The user switches reminders off on one
phone and keeps getting them on the other, which is exactly the complaint that
motivated the single-app rebuild.

- `GET/PUT /me/notification-preferences/`
- The device store becomes a cache of the server's answer, not the truth
- Reminder tasks already read the profile; this makes the app agree with them

**Acceptance:** switching off on one device changes the other on next fetch;
the reminder task and the settings screen cannot disagree — all tested.

**Six categories, not two.** The app had six granular switches and the
server had two coarse flags, which is a mapping nobody could implement
honestly. Both are now six, stored per key, so "reminders" means one thing
in both places.

**A row means the account has an opinion; no row means the default.** Every
existing account keeps what it had, and nothing is opted in on anyone's
behalf.

**Booking confirmations and messages cannot be switched off**, whatever is
sent. Letting someone opt out of being told their own appointment was
cancelled would be a bug with a settings screen in front of it.

**The coarse profile flags are rewritten from the granular answer**, because
the reminder task filters on `reminders_enabled` in several places. Two
sources of truth would drift again the moment a new caller appeared.

**In the app** the store is now a cache: switches render instantly and work
offline, every change writes through, and the server's answer replaces the
cache wholesale whenever it answers. The screen says "Syncing with your
account…" until it has, because a switch that is confidently wrong is worse
than one that admits it is guessing.

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
a second; a reply that says "cancel" cancels the booking — tested, 36 API tests
and 3 app tests.

**A message is keyed on what it is about, not when it was sent.**
`booking-confirm:<reference>`, with a unique index behind it. So "send the
confirmation" is safe to call from a view, a capture, a webhook redelivery and
a retry task without anybody having to decide which of them is first. WhatsApp
is charged per message, and a customer who gets the same text four times is a
customer who stops reading them.

**Two separate mechanisms, because they fail differently.** The local index
stops *our* duplicates; the provider's own idempotency token stops the one
where the request succeeded and the connection dropped before we found out —
which is exactly the case where we retry.

**Sent when the deposit is captured, not when the booking is created.** A
booking exists while it is unpaid, and "you're booked" is a thing the customer
will hold us to. Capture is the first moment it is true.

**Replies are parsed how people actually write.** `cancel`, `CANCEL`, `pls
cancel my booking`, `I can't make it`, `won't be able to come` all cancel.
Only one of those is on any list anybody writes. A parser that only knows the
first is a booking that does not get cancelled.

**"thanks" is not a cancellation.** Somebody acknowledging a message is not
giving an instruction, and after a cancellation, reading it as one is how a
booking gets cancelled twice.

**A reply we cannot parse is kept anyway.** It is still a reply from a
customer; discarding it means the next person to look has no idea anybody
tried.

**Delivery status is only ever moved forward.** Providers send these out of
order, so a late "sent" cannot walk a "delivered" back to looking undelivered -
which is how a dashboard ends up reporting 0% delivery for messages that
arrived. "Sent" means the gateway accepted it, not that a human saw it, and the
row says so.

**Every event is acknowledged, even the ones we ignore.** A non-2xx makes the
provider redeliver forever, including for events we deliberately do nothing
with. Rescheduling is left to a person: a reschedule needs a new time, and
nobody who typed the word has said which one.

**Nothing here breaks a booking.** A provider that is down, a timeout, a
number that will not parse - the appointment still happens. A gateway outage
must not undo a capture or roll back a slot somebody has already paid for.

---

# P4 — Provider tools

## P4.1 Server-side provider analytics

**Status:** done

The provider dashboard computes three numbers **on the device** from the
bookings list. That is wrong three ways: it is wrong if you page beyond the
first page, wrong if the device is offline, and it cannot show anything about
periods you have to page backwards through.

- Revenue, bookings, no-show rate, rebooking rate, utilisation, per service
- Over a period, compared with the previous one
- Computed in SQL, paged properly, no client arithmetic

**Acceptance:** the numbers match what the bookings list contains across
*every* page, not the first.

- `GET /api/v1/providers/me/analytics/?days=30` — `days` must be one of
  7/30/90/365, refused rather than silently coerced
- Money is read from the ledger, not recomputed from booking totals, so tips
  and manual adjustments are included; tips count as earnings and carry no fee
- `percent` is `null` when the previous window was empty. "Up from nothing" is
  not a percentage
- Rates ship with the counts behind them: "50% returning" means something very
  different at four customers than at four hundred
- Dashboard shows earned, the trend, completion, returning and no-show rates,
  and what earns, with a 7/30/90-day switch
- Four bugs found and fixed while testing, each with the test that catches it:
  booked minutes came out in seconds; tips were excluded from earnings; the
  rebooking query excluded every customer it could have counted, pinning the
  rate at zero; and the counts behind the rate were never exposed, which is
  why that went unnoticed

### The `?open_now=` filter, which disagreed with the shop's own page

`ProviderProfile.tz()` resolves shop, then account, then server. The search
filter resolved shop, then UTC. A shop that never set its own zone but whose
owner had one was filtered by the wrong clock, so `?open_now=true` could hide a
shop that was open. Every existing test set both zones to the same value, or
both to nothing, so the two had nowhere to disagree. There is now a frozen-clock
test, across all three cases in the chain, asserting the filter agrees with
`is_open_at`.

## P4.2 Client notes and consultation forms

**Status:** done

The provider sees `Booking.notes` — a 500-character free-text box the
customer fills in at booking. Everything a barber actually needs to know
before a client sits down is missing.

- Provider-authored consultation forms attached to a service
- Customer answers at booking; the provider sees answers on the booking
- Sensitive answers flagged so they are shown only to that provider

**Acceptance:** a form attached to "Colour service" is answered at booking
and visible on the provider's booking detail — tested, 29 API tests and 12 app
tests.

**Attached to services, not to the shop.** What a barber needs to know about a
beard trim is not what they need to know about a full colour change. A form with
nothing attached is never asked, so the app refuses to save one rather than
letting it look successful and do nothing forever.

**Asked before committing, not after.** The customer can see the whole form
before they book, which is the only way it can be consent rather than a
surprise — and it means a required question stops the booking on the checkout
screen instead of surfacing at the shop.

**Answers are only accepted for questions that apply.** A request may not ask
a shop's booking arbitrary questions, which would make the form a suggestion
rather than a contract. A question from another shop, or from a service not in
this booking, is refused.

**Everything about an answer is frozen.** The question's wording and its
sensitive flag are copied onto the answer. Rewording a question next month must
not rewrite what somebody said three weeks ago, and a provider who realises a
question was over-broad must not be able to un-flag it and make every answer to
it readable by the customer retroactively — which is exactly the moment the
customer trusted the flag.

**A sensitive answer is shown to the provider of that booking and to nobody
else.** Not the customer, not another shop, not a staff member elsewhere. It is
*withheld* rather than replaced with "hidden": a placeholder row still confirms
how many questions there were and which were private, which is itself the
information the flag exists to protect.

**Not every question is a text box.** A yes/no is two taps and a pick-one is a
list, because a barber reading down a column of clients wants answers at a
glance, not paragraphs — and asking "have you had colour before" with a
keyboard gets one-word answers to questions that needed a sentence.

## P4.3 Tips

**Status:** done

Universal in this category, absent here. Complicated by our fee model — a tip
is not part of the booking total, so it must not touch the platform fee.

- Customer adds a tip at the end of a completed booking
- Paid through Razorpay separately from the booking
- Provider sees per-barber tips, and they are excluded from the fee

**Acceptance:** a tip is paid once, recorded against the staff member, and
never counted as platform revenue — tested, 21 tests.

**Offered where the review is**, on the screen for an appointment that already
happened. That is the only moment somebody is thinking about the person who just
cut their hair, and a tip asked for somewhere else is a tip that never arrives.
It does not appear on a booking that has not happened.

**A partial capture is not possible here.** `capture()` is one transaction, so a
failure while recording the tip rolls the payment status back as well. Checked
rather than assumed: a test fails the second half on purpose and asserts
nothing was left captured, then asserts the retry afterwards still pays out.

**What it did find**, one layer down: `capture()` returned early when the object
in hand said captured, but a rolled-back attempt leaves that object still
claiming it was while the row says otherwise. A retry holding the same instance
skipped the work entirely — captured payment, no tip, nobody credited. It now
re-reads the status, costing a query only on the retry path.

**A tip is not part of what the appointment cost**, and almost everything here
follows from refusing to pretend otherwise. It does not touch the booking's
total, the deposit split, or the booking's status. Folding it into the total
would move all three, plus anything measured off "total" — and a completed
appointment would look like it had not been paid.

**A separate payment and a separate order.** The booking is already paid and
closed; moving money on it again is the thing to avoid.

**The provider keeps all of it.** One ledger entry, no fee line. A percentage
on somebody's thank-you is not a fee. There is a test that tips ₹1000 and
asserts the provider's balance goes up by 1000 rather than 990 — so the
decision is written down rather than assumed.

**One tip per booking**, from a constraint that already existed for every other
payment kind. It protects against a retried flow charging twice, and a second
tip is better made on the next appointment than by loosening something every
payment relies on.

**Grouped by barber**, because a figure for the shop as a whole cannot be acted
on by the person whose chair it was.

**Still to do:** no app screen to leave one.

## P4.4 Promo and discount codes

**Status:** done

- Percentage or fixed amount, with an expiry and a usage cap
- Scoped to a shop, a service, or the platform
- Applied server-side at quote time; the client sends only the code
- The fee is calculated on the discounted amount, and that is stated plainly

**Acceptance:** an expired code is refused at quote and at checkout; the
discount reduces the fee base and the customer is shown that — tested, 27
tests.

**Quote and checkout share one pricing function**, so a code that expires
between them is caught at both rather than being quietly ignored at one. A
test asserts the quoted total and the paid total are identical.

**Applied in the app, at the quote rather than at payment.** The code is sent
to be resolved and the server says what it did, so the customer sees a total
that already has the discount in it instead of finding out at the payment
screen. The same code travels into the booking request, so the price quoted
and the price charged cannot drift apart. The app never computes a discount.

**The fee is taken on the discounted amount, and the reduced fee is shown
beside the full one.** The alternative — holding the fee at its full amount —
shows a total nobody can reconcile from the numbers on the screen. The
platform ends up funding part of its own promotion, which is cheaper than a
support ticket.

**The percentage cap does not apply to a fixed amount.** It exists to stop a
mistyped "90% off" giving away the chair. A shop offering ₹500 off has said
what it means, and reducing that to the cap is the code not doing its job; a
fixed amount is bounded by the basket instead.

**Codes are normalised on the way in**, so somebody typing one into a phone
gets it to work. A lookup that silently misses is indistinguishable from "this
code does not work".

**Every refusal has its own sentence.** "Expired" and "used up" and "does not
apply here" are different problems with different fixes, and calling all three
"invalid code" is a lie the customer will check.

**Still to do:** no app screen for entering a code at checkout.

## P4.5 Review reminders and photo reviews

**Status:** done

Reviews exist and are tied to completed bookings, so the trust signal is
already right. Nobody is being asked for one.

- A Celery nudge after a completed booking
- Photo upload on a review
- Reply already exists; notify the provider when one arrives
- A provider can request removal only for abuse, not for being rated badly

**Acceptance:** a completed booking is nudged once; a review with a photo
renders on the shop page — tested, 22 tests.

### Three bugs the existing tests could not see

- **The shop page rendered `review.body`.** The field is `comment`, so every
  review showed a star rating and no words under it. Django treats a missing
  attribute as empty rather than raising, so nothing looked broken.
- **The photo was never rendered at all.** The acceptance criterion was being
  met by a JSON response nobody reads. There is now a test that fetches the
  page.
- **The opt-out could never be false.** It required three notification
  categories to be off at once, and `bookingChanges` is required, so the server
  forces it back on. Nobody who turned notifications off was ever spared a
  review request. It now follows the reminders switch, which is optional and is
  the category somebody turns off when they want to stop being buzzed about
  their own appointments.

**The window is one day to a month.** Immediately after an appointment nobody
has an opinion yet; three months on, the review is about the platform rather
than the haircut.

**Once per booking, ever, recorded in its own table.** "Have we asked?" cannot
be derived from booking dates — a customer who reviews and one who never will
look identical from the appointment's side, and a second nudge to somebody who
has already declined is how the whole notification category gets turned off.

**A booking that is already reviewed is never nudged.** Asking for something
they have done is nagging.

**Somebody with no device is not recorded as asked**, or a failed push means
they are never asked at all.

**A provider can report a review only for abuse** — harassment, spam, or one
about somebody else. The rule lives in one function and the view checks the
reason it was *given*, not the one stored on the row.

**The provider is told when a review arrives.** Reviews are the main thing a
provider cannot see coming, and an unanswered one — especially a bad one — is
worse than the review.

Three bugs the tests found:

- **The two bounds of the window were crossed**, so a booking two days old was
  excluded and nobody was ever asked.
- **The removal check read the stored reason, not the submitted one.** Empty
  the first time and set afterwards, so the *first* report was refused and
  every later one allowed.
- **The photo was validated and then dropped.** Adding the field to the
  serializer is not enough when `create()` writes its fields out by name.

---

# P5 — Platform

## P5.1 Idempotency keys on payment endpoints

**Status:** done

`capture()` is internally idempotent for webhook retries, but a client
retrying `POST /payments/verify/` on a flaky connection is not protected. The
mobile app explicitly disables mutation retries as "not idempotent" — this is
the fix that would let it turn them back on.

- `Idempotency-Key` header, stored with the request fingerprint
- A repeat with the same key returns the first response
- A repeat with the same key and a *different* body is a 409

**Acceptance:** two identical verify calls create one capture; the same key
with a different body is rejected — tested.

### The part that was wrong the first time

Three bugs, found by writing the tests that the previous version was missing.
The original note here claimed the feature was done; it was not safe to retry.

- **The key was claimed after the work, not before.** The record was written
  once the view had already run, so two requests arriving together both found
  nothing, both ran the view, and both captured the payment. Whoever won the
  insert kept the response and the other was thrown away — the money still
  moved twice. The reservation now goes in first, and the unique insert is the
  lock: the loser replays the winner's answer or is told to come back, and
  never does the work. Reproduced by firing a second request from inside the
  first one.
- **The key was regenerated on every retry.** React Query re-invokes the
  mutation function per attempt, and the key was built inside it, so each
  attempt was an unrelated request as far as the server was concerned. Retries
  were working exactly as designed and delivering precisely the wrong result.
  The key now travels in the mutation variables, so it is fixed for the whole
  operation and a new user-initiated call gets a new one.
- **Two of the three retried endpoints ignored the header entirely.** Booking
  creation and order creation were unguarded, so a retry booked the same slot
  twice or produced a second Razorpay order. The header was travelling all the
  way to the server and being dropped on the floor.

Also fixed here: the stale-reschedule tests were clock-dependent — "today at
ten" is in the past for most of the day, so four of them passed only when the
suite happened to run before 10:00 and failed for the other sixteen hours. They
now anchor to the clock and land inside working hours, verified green across a
25-hour timezone spread.

**The body is fingerprinted, and that is what makes it safe rather than
merely convenient.** A *different* request wearing a used key is not a retry,
it is a mistake; answering it with the first response would hand back
somebody else's receipt, which is worse than refusing.

**Keyed JSON, so body ordering does not matter.** A client is not obliged to
serialise a dict consistently, and two bodies that differ only in ordering
are the same request.

**Scoped to the account as well as the endpoint.** Two people on one device, or
one person signing out and back in, must not collide.

**The stored response is replayed byte for byte.** Recomputing it could produce
something subtly different from what the customer was already shown.

**Only successes are recorded.** A client that genuinely failed should be free
to try again — a retried failure is the normal case, not the dangerous one.

**A key older than a day is not replayed**, so a client that keys per *attempt*
rather than per *operation* is not locked out of the endpoint forever.

**No key means no change.** Nothing is required of any existing client.

**In the app.** Every write now carries an `Idempotency-Key`, so a retried
booking or verify replays the first response instead of doing the thing
twice. **Mutation retries are switched back on** — they were disabled with a
comment saying mutations are not idempotent, which was true and is the reason
a dropped connection during checkout used to lose the booking.

The query layer still does not retry a 4xx. A 400 will be a 400 again, and
retrying it only delays the error the user needs to see.

The old test that asserted `mutations.retry === false` was not deleted when
the behaviour changed; it was rewritten to assert the new one, because the
comment explaining *why* it was false is the thing that would otherwise get
lost.

## P5.2 API keys for third parties

**Status:** todo

Only session/token auth exists. A POS integration or an owner's dashboard
cannot talk to this API without impersonating a user, so the platform cannot be
embedded anywhere.

- Scoped keys per integrator, hashed at rest
- Scopes matching the read/write split
- Rate limits per key, and usage visible to the key's owner

**Acceptance:** a key with read scope cannot write; a revoked key stops
working immediately — tested, 24 API tests and 12 app tests.

**The key is hashed at rest, and salted.** A database dump must not hand
anybody the ability to act as a customer. Plaintext keys in a table are a
breach that survives the breach.

**A key acts as its owner, never as itself.** There is no "the API" identity
that can read everybody. A leaked key reads one customer's bookings, which is a
bad day rather than a catastrophe.

**The secret is shown once and cannot be recovered.** A system that can show
you an existing key is a system whose database is one dump away from being a
credential store. The app says so at the moment it is shown, because a user
who does not know the secret is gone for good will not copy it, and the
integration silently fails later.

**An endpoint nobody marked as key-reachable is not reachable with a key** —
refused at the authenticator rather than by a permission class, so it is closed
by default. Anything else is one forgotten decorator away from a hole somebody
finds by reading the URL list.

**Revocation is a flag, not a delete, and it is immediate.** The lookup happens
per request against live rows, so a revoked key is refused on its very next
call. The row survives, because somebody deciding to stop trusting an
integration should not also delete the record of what it once did.

**An unknown prefix and a wrong secret give the same error**, or the endpoint
is a way to discover which keys exist.

**Rate limits belong to the credential, not the address.** A POS integration
sits behind a shop's office NAT and every other caller in that building shares
its IP; limiting by IP means one integrator saturating its own budget locks out
everybody behind the same router.

**Scopes are deliberately coarse.** Anything finer than read/write invites
"which is this endpoint again?", and a key that can only read is the default.

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
a deposit, and the recommendation is advisory, not enforced — tested, 28 API
tests and 8 app tests.

**Nothing is said until there are three appointments.** One no-show out of one
booking is a hundred per cent rate and means nothing at all, and a system that
flags on the first one trains every provider to ignore the flag. A customer
with no history is **unknown**, not low-risk: a shop that treats unknown as
risky ends up demanding deposits from every new customer.

**The recommendation changes nothing.** The quote carries it, the booking
carries the same figure, and the deposit actually taken stays whatever the
service's own policy says. A score that quietly raises what somebody pays ends
in a chargeback with the shop none the wiser. Tested by booking as a
two-no-show customer and asserting the deposit is still zero.

**Cancelling is not not turning up.** A shop cancelling an appointment is
counted in the record but never held against the customer, and a customer who
churns slots gets a *low* flag and a 25% suggestion rather than the treatment a
no-show run gets.

**Unknown, clean and risky are three different sentences.** They read
differently in the app on purpose. "Not enough history" and "nothing here
stands out" collapse into the same string if you are not careful, and the
moment they do, a customer with twelve clean appointments reads as a customer
we know nothing about.

**Flags are flags, not bans.** The sweep raises them; a person decides what
they mean. A flag can be cleared, and clearing keeps the record — otherwise a
bad month is a life sentence and a customer who fixed whatever it was has no
way of showing that.

**The cached profile is a cache.** Everything is recomputed from bookings, like
the money ledger and the points ledger. A stored counter that drifts from the
bookings is a counter that denies somebody an appointment they had every right
to.

## P5.4 Provider CSV export

**Status:** todo

Every salon runs on a spreadsheet. If their data cannot leave our product
they will maintain two records, and ours will be the stale one.

- Bookings, revenue and clients as CSV
- Generated by a Celery job and emailed, because a year of bookings is not a
  synchronous response
- Payout history alongside

**Acceptance:** an export contains every booking in the period, not just the
first page — tested, 25 API tests and 9 app tests, including 250 bookings
against a 20-per-page list.

**The file is not kept.** It goes out by email and is not stored. A copy of a
salon's data sitting on a server is a copy somebody eventually forwards, and the
row that survives is the *request* - who asked, for what period, and whether it
arrived. Without it "the export never came" is unactionable.

**No pagination, anywhere.** Every dataset streams off the cursor. Anything that
fetched a page and then iterated in Python passes a glance at the code and fails
a shop with four hundred bookings, which is why the test is 250 rows rather than
three.

**Amounts come out twice**: plain paise, and a formatted column beside it. A
spreadsheet that opens where the decimal separator is a comma turns a column of
rupees into one enormous number.

**Free text cannot become a formula.** A booking note typed as `=cmd()` must
not become a formula in somebody's spreadsheet, so cells starting `=`, `+`, `-`
or `@` are prefixed with an apostrophe. Newlines in a note are flattened, or a
multi-line note becomes two rows in some readers.

**Dates are given twice too** - UTC and the shop's own clock - because those are
not the same and the local one is the one they booked against.

**A refusal sends nothing at all.** Too many rows fails before the first file
is emailed, so a request that cannot be satisfied in full never arrives as a
partial file that looks complete.

**The worker never emails twice**, even if it is redelivered, because the task
checks the row's status before doing anything.

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

**Status:** done

Shop hours are naive `TimeField`s and the Celery beat runs on UTC. Works for a
single-country marketplace and silently corrupts once it is not one. The
customer profile already carries `timezone_name`; the shop does not.

- A timezone on the shop, defaulting from the account
- Working hours interpreted in the shop's timezone
- Reminder lead times computed in local time, so a 3-hour lead before a 09:00
  appointment is 06:00 local and not 06:00 UTC

**Acceptance:** a shop in a non-UTC timezone reads its hours correctly —
tested, 21 tests, including a shop at UTC+5:45 so the day does not start on
the hour.

**The zone was there, writable by nobody.** The field existed and the search
filter used it, but the provider's own record did not expose it — not to read,
not to write — so a barber saying "I open at nine" had no way to say which nine
and no way to check which one the shop was using. It is now part of the shop
record, and the resolved zone is written back alongside the one that was set,
because the one the hours are read in is not always the one that was saved.

**An unresolvable zone is refused at the door.** Stored unvalidated it becomes
a 500 the first time somebody searches `?open_now=true`, which is the moment it
matters most and the least convenient moment to find out it was wrong.

**The bug was that nothing anchored the hours at all.** Every "local time" in
the codebase meant *the server's* local time: `timezone.localtime()`. Correct
for a single-country marketplace, quietly wrong the moment a second one
exists. A Bengaluru shop opening at 09:00, checked against UTC, opens at
14:30 and closes at 02:30 the next morning.

Resolved shop, then account, then server. A zone the host no longer knows
about falls through rather than 500-ing every request that shop receives.

**`open_now` is filtered per row, in SQL.** The obvious version compares one
`now.time()` against every shop, which cannot be right across zones. The
database is asked for each row's own wall clock
(`CURRENT_TIMESTAMP AT TIME ZONE COALESCE(NULLIF(timezone_name, ''), 'UTC')`),
so the filter stays in the query and stays correct with pagination.

**Reminder lead times were already right.** A lead is an absolute number of
hours before a UTC instant, so "three hours before a 09:00 appointment is
06:00 local" holds by construction. What was broken was the hour the
appointment was *judged* at.

**Still to do:** the app renders appointment times in the device's zone rather
than the shop's.

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
