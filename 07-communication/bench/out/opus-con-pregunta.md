No: with the code you describe, a retry can charge twice.

The idempotency key (the identifier that tells the bank "this is the same order, don't charge it again") gets created inside the loop. Each attempt sends a different key, so the bank sees different payments. Think of a coat-check ticket: the key is the ticket number and the payment is the coat, and the same number always gets you back the same coat. Here you ask for a new number on every attempt, so you get handed a new coat every time. Where the comparison breaks: at the coat check you instantly see you're holding two coats; the second charge can show up hours later on the customer's statement.

- `PaymentRetry.kt:52` @ 9f3e2a1 calls `newIdempotencyKey()` on every iteration: one attempt, one new key.
- The dangerous case is the ambiguous failure, a timeout or a network drop with the charge already accepted at the bank. The retry with a new key charges it again.
- A clear rejection, like a declined card, is indeed safe to retry. The problem is the code doesn't separate the two cases.
- The fix is to generate the key once per payment intent, before the loop, and reuse that same key on every retry.
- With no test for the retry, nobody catches the regression if someone moves the call back inside the loop.

Irreversible risk: money charged twice to the customer. Undoing it requires a manual refund, and the customer has already seen the charge.

Next step: take `newIdempotencyKey()` out of the loop and add a test that simulates a timeout and retry, and checks that the provider receives the same key on both sends. Until that's in place, disable automatic retry or query the payment status before retrying.

Not tested: I haven't run the code or seen the provider's actual response. I also don't know which payment provider you use or how long it keeps the key.

## Technical detail

- `PaymentRetry.kt:52` @ 9f3e2a1 invokes `newIdempotencyKey()` inside the retry loop. [Assumed] as you describe it in your message; I haven't read the file.
- One key per attempt makes the provider treat each retry as a new operation, instead of returning the stored response from the first send. [Inferred] from the standard behavior of an idempotent API.
- No test covers the retry. [Assumed] per your message.
- Proposed fix: one key per `PaymentIntent`, created before the loop and persisted alongside the attempt so it survives an app or terminal restart. [Inferred]
- The window during which the provider remembers an already-used key. [Unknown] Depends on the provider; check their documentation before setting the number of retries and the time between them.
