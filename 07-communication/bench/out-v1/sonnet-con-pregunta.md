No, today you can't retry without risk of charging twice.

The idempotency key only protects against a double charge if it's the same across every retry of the same payment. In your code, a new key gets generated on every pass of the loop. For the gateway, each retry is then a different payment. If the first attempt did charge but the response was lost to a network drop, the second attempt charges again.

Next step:
- Move key generation outside the loop, so every logical payment attempt uses a single key.
- Add a test that retries over a simulated failure and confirms the key doesn't change between calls.

## Technical detail

- [Measured] `PaymentRetry.kt:52` (commit `9f3e2a1`) calls `newIdempotencyKey()` inside the retry loop, on every iteration.
- [Inferred] Every retry sends a different key to the gateway, which treats it as a new payment instead of a retry.
- [Assumed] The gateway deduplicates payments only when it receives the same idempotency key; this depends on the specific provider and isn't confirmed here.
- Not tested: no test covers the retry path, so this behavior isn't verified against a real network failure.
