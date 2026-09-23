Yes, there is risk. The SDK regenerates the idempotency key on every retry instead of reusing it.

An idempotency key must stay the same across every attempt of the same request; if it changes, the server sees different attempts and charges each one. Your SDK does the opposite: it generates a new key on every iteration of the retry loop.

The symptom: duplicated or tripled payments after failed retries. The cause: `newIdempotencyKey()` is called inside the loop instead of before it [Inferred from PaymentRetry.kt:52 @ 9f3e2a1]. What it is not: a concurrency issue, nor a network failure.

Next step: refactor to generate the key before the loop and reuse it on every iteration. Add a test that triggers two consecutive retries, captures both HTTP requests, and confirms they carry the same key.

Not tested: whether there are other places in your code that regenerate idempotency keys; how many duplicate charges have already happened.
