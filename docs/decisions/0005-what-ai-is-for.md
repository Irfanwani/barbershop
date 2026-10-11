# 0005. What the AI is and is not for

- **Status**: Accepted
- **Date**: 2026-10-11

## Context

"Add AI" is not a requirement. It is a wish that arrives without a user
problem attached, and the failure mode is a chatbot bolted onto a booking app
that nobody uses, cannot trust with a cancellation, and that costs money on
every request.

This platform's users have specific, articulable problems:

- "I do not know what a haircut should cost here." — real, and already solved
  by aggregated prices.
- "I do not know which shop suits me." — real, and mostly answered by reviews,
  which are already tied to completed bookings.
- "I have a rash on my scalp and the last place I went did that." — real, and
  genuinely hard to answer with keyword search.
- "Cancel my appointment." — real, and completely wrong to route through a
  language model when a button does it correctly.

Anything that does not sit on that list is decoration.

## Decision

**Two features, both narrow, both replaceable.**

### 1. Symptom → service suggestions

A customer describes what they want in their own words and gets back services
and shops. This is the one place a language model earns its keep: matching
"I want it shorter but not buzzed" to a service menu is a semantic problem
that `ILIKE` cannot do, and getting it wrong costs nothing — the worst outcome
is suggestions that are not relevant.

Built as a *retrieval* problem, not a generation one. The model is only ever
allowed to choose from a list of service and shop ids the backend supplied.
It cannot invent a price, cannot name a shop that is closed, and cannot change
a booking. Every suggestion is a row that already existed.

### 2. Review summarisation

A shop's fifty reviews, condensed into "mostly does good fades, some say they
run late". This is summarising text the platform already hosts, about the
platform's own merchants, and a wrong summary is corrected by the merchant.

**Not building:**

- A conversational booking assistant. Booking is a five-tap flow; a chat
  interface to do it is slower, harder to test, and unable to say "I have
  cancelled BK-7QK4M2" with the confidence a button can.
- An AI-generated reply on a provider's behalf. Providers write their own
  copy or they do not.
- Anything that touches money. Pricing, payment and booking transitions stay
  server-side and deterministic, per [0003](./0003-server-authoritative-pricing.md).
- A chatbot on the marketing site. It would have to answer questions about
  shops, which means either a stale cache or a live call per visitor.

## Consequences

**What this makes easy.** Adding a second model is a new task class, not a new
system. Both features degrade to a plain keyword search when no provider is
configured, so neither is a hard dependency and neither can take the site down.

**What this makes hard.** The retrieval step is the part that has to be right,
and it needs a real evaluation set of "customer said X, the right answer is Y"
pairs. That is a day of work that has not been done yet, and until it exists
the suggestion quality is a guess.

**What we give up.** A general assistant would have been more impressive to
demo and worse to use.