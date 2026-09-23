No, not today: with that code the retry can charge twice.

The idempotency key is what tells the bank "this charge and the previous one are the same." In `PaymentRetry.kt:52` that key gets generated inside the loop, so every attempt sends a different key and the bank treats them as different charges. If the first attempt did go through and only the response got lost, the second one charges again.

It's like ordering at a ticket counter: if you repeat the order with the same receipt number, you get the same ticket; if you make up a new number every time, they charge you for another ticket. Unlike the ticket counter, here you don't see the duplicate until reconciliation.

Next step: generate the key only once before the loop and reuse it on every attempt, and add a test that runs two attempts and checks that both send the same key.

## Technical detail

- [Measured] `PaymentRetry.kt:52` @ 9f3e2a1 calls `newIdempotencyKey()` inside every iteration of the retry loop. Source: context provided in the query.
- [Measured] No test covers the retry. Source: context provided in the query.
- [Inferred] With a different key per attempt, the provider can't deduplicate: idempotency depends on the key staying stable for the same operation.
- [Unknown] Whether the payment provider applies some additional deduplication (by amount, card, and time window) that would cushion the duplicate. Found in their idempotency documentation and with a sandbox test: same payment, two different keys, check whether it creates two charges.
- [Unknown] Whether other retry paths (manual retry by the cashier, resend from a queue) share this same defect. Found by searching for every call to `newIdempotencyKey()`.
- Not tested: I haven't run the code or reviewed the repository; the whole conclusion comes from the snippet you describe.
