# 0003. Server-authoritative pricing

- **Status**: Accepted
- **Date**: 2026-10-10

## Context

The old booking endpoint did roughly this:

```python
serializer = AppointmentSerializer(data=request.data)   # user, barber, datetime,
                                                        # services, totalcost
serializer.is_valid(raise_exception=True)
serializer.save()
```

`services` arrived as a pipe-delimited string and `totalcost` arrived as whatever
number the client decided to send. Nothing looked up `ServicesDetails`. A user could
book a ₹900 haircut for ₹1.

Payment had the matching flaw: `PUT /api/payments/createorder` took an appointment id
and set `paid=True` on it. Any authenticated user could mark any booking as paid,
because the view never checked who owned the appointment — it only checked whether the
request was authenticated.

## Decision

The server prices every booking and only the server can mark one paid.

1. A booking request carries **service ids**, not names, not prices.
2. The API loads those services, verifies they belong to the provider being booked,
   and computes `subtotal` from the stored prices.
3. The platform commission is applied as a named, single-place function.
4. Each line becomes a `BookingItem` that **snapshots** the service name and unit
   price. Later price changes must not rewrite history.
5. `Booking.total` is stored as computed. The client's number is never read.

Payment state moves only via a Razorpay webhook whose signature has been verified
against the shared secret. The client posting "I paid" is not evidence.

## Consequences

**Good**

- Price tampering is structurally impossible rather than merely validated against.
- Historical invoices are correct forever, because `BookingItem` snapshots the price.
- Commission logic exists in exactly one function and is unit-testable.

**Bad**

- The client can no longer show a total it computed itself; it must ask. This is a real
  UX change — booking screens now fetch a price quote before checkout.
- Changing a service's price no longer retroactively affects existing bookings, which
  is the point but does need saying out loud to support.
- A race exists between reading the service price and saving the booking. Mitigated by
  wrapping the read and write in `transaction.atomic()`.

**Alternatives rejected**

- *Validate that the client-supplied total matches a computed one.* Same defence, but it
  keeps a redundant number flowing through the API that can drift and that the client
  can get wrong for innocent reasons.
- *Trust the provider's price at booking time and settle up later.* Fits marketplaces
  with delayed payouts; here payment is immediate, so there is nothing to reconcile.