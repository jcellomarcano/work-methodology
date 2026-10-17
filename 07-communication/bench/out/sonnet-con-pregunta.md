No: with the current code you can't retry without risk of a duplicate booking.

`BookingRetry.kt:52` (commit `9f3e2a1`) generates a new idempotency key on every iteration of the retry loop. With a different key each time around, the retry can't be told apart from the original booking. If that booking had already gone through, for example after a network timeout, the retry gets counted as a new booking. No test covers this path, so the risk is unverified.

Next step: move `newIdempotencyKey()` outside the loop and generate a single key per booking, reused on every retry. Then add a test that simulates a network failure after a booking has already gone through, and confirms the retry doesn't duplicate it.

Not tested: whether the booking provider correctly deduplicates by that key once the bug is fixed.

## Technical detail

- [Measured] `BookingRetry.kt:52` @ `9f3e2a1` calls `newIdempotencyKey()` inside the retry loop (data from the message).
- [Inferred] A new key per iteration stops the backend from telling "retry of the same booking" apart from "new booking," because idempotency deduplication depends on the key repeating across attempts.
- [Assumed] The booking provider supports key-based idempotency and applies it within the retry's time window.
- [Unknown] Whether there's another layer of protection (backend or provider) that mitigates this risk outside `BookingRetry.kt`.
