No: with the current code you can't retry without risk of a duplicate charge.

`PaymentRetry.kt:52` (commit `9f3e2a1`) generates a new idempotency key on every iteration of the retry loop. With a different key each time around, the retry can't be told apart from the original payment. If that payment had already gone through, for example after a network timeout, the retry gets counted as a new charge. No test covers this path, so the risk is unverified.

Next step: move `newIdempotencyKey()` outside the loop and generate a single key per payment, reused on every retry. Then add a test that simulates a network failure after a charge has already gone through, and confirms the retry doesn't duplicate it.

Not tested: whether the payment processor correctly deduplicates by that key once the bug is fixed.

## Technical detail

- [Measured] `PaymentRetry.kt:52` @ `9f3e2a1` calls `newIdempotencyKey()` inside the retry loop (data from the message).
- [Inferred] A new key per iteration stops the backend from telling "retry of the same payment" apart from "new payment," because idempotency deduplication depends on the key repeating across attempts.
- [Assumed] The payment processor supports key-based idempotency and applies it within the retry's time window.
- [Unknown] Whether there's another layer of protection (backend or processor) that mitigates this risk outside `PaymentRetry.kt`.
