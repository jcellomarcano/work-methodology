Hi,

Short version: as it's implemented now, you shouldn't retry. The very mechanism that's supposed to protect you from double bookings is broken.

Idempotency only works if the same key travels across every attempt of a single booking operation. In `BookingRetry.kt:52` (commit `9f3e2a1`) I see `newIdempotencyKey()` being called on every loop iteration, meaning each retry generates a new key. For the provider's backend, that isn't "the same booking retried": it's N distinct, independent requests, each one perfectly valid to process and booking. If the first attempt actually did complete on the bank's side but the response got lost or arrived late (timeout, network drop, etc.), the retry with a new key can generate a real second booking. The typical double-booking case is exactly that: network failure/timeout, not an explicit booking rejection.

What I'd change before touching the retry flow in production:

1. Generate the idempotency key **only once per user booking attempt**, outside the retry loop, not inside it.
2. Persist it alongside the order/transaction (even if it's only in the SDK's memory/local state) so it survives across retries, even if the process restarts or the user closes and reopens the booking screen.
3. Reuse that same key on every call in the loop as long as it's the same booking attempt. A new key only gets generated if the user explicitly starts a new booking attempt (new seat, new party, etc.), not on every automatic retry of the same booking.
4. Add tests that specifically cover this, since right now there are none: (a) that the key stays stable across retries of the same transaction, (b) that two calls with the same key and the same payload don't generate two bookings at the PSP (or at least that the client correctly handles the idempotent response), and (c) the case of a timeout on attempt 1 followed by success on attempt 2, verifying there's no duplicate booking.

Until that's fixed and tested, I'd treat automatic retries as unsafe against duplicates, and if you need a quick stopgap, I'd force key generation before the loop as a minimal patch while the full fix and its tests get ready.

Any questions about implementing the fix, let me know and we'll go through it together.

Best.
