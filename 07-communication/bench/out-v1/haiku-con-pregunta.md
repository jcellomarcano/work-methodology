No, there is risk. The idempotency key gets regenerated on every retry, so the server sees each attempt as a different transaction.

An idempotency key works if it stays the same across every retry of the same payment. Your SDK generates a new one on line 52 of every iteration, so `newIdempotencyKey()` returns a different value each time. The server can't deduplicate and processes both charges.

With no test verifying this, the bug stays latent. When two requests fall within the retry window, they get duplicated.

**Next step:** generate the key only once, outside the loop. Pass the same one on every retry.

## Technical detail

- `PaymentRetry.kt:52` generates a new key on every iteration inside the loop [Verified in context]. Idempotency requires that key to stay constant for the same transaction [Standard specification HTTP 429, RFC 9110].
- No retry test exists, so the behavior isn't guaranteed [Assumed: no coverage in the suite].
- Fix path: pull `newIdempotencyKey()` out of the loop, or tie the key to the transaction's identity (user + amount + timestamp) once, before retrying.
