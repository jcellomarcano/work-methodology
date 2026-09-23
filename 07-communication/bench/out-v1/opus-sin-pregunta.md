No, as it stands now it isn't safe: with that code there is a real risk of charging twice.

**Why**

The idempotency key exists precisely so the server can recognize that two requests are *the same* charge and not two different charges. If `PaymentRetry.kt:52` calls `newIdempotencyKey()` inside the loop, every retry travels with a new key, and from the processor's side that isn't a retry: it's N independent payments. The protection gets cancelled out in exactly the scenario it was designed for.

The case that bites you is the worst of all, and it isn't rare: the first request **does** arrive and the charge gets authorized, but the response gets lost (timeout, the POS's network drops, the process dies before reading the ACK). Your SDK interprets that as a failure, retries with a new key, and the customer ends up with two charges. A "failure" observed from the client doesn't mean it wasn't charged.

**The fix**

The key must be generated **only once per payment attempt**, outside the loop, and reused identically across every retry of that operation:

- Generate the key when the charge intent is created (when the cashier taps "charge"), not when the request is sent.
- Persist it alongside the operation, not just in memory: if the app or the terminal restarts mid-retry, recovery must keep using the same key, not a new one.
- Derive it from something stable about the transaction (the sale id) or generate a UUID and store it; what matters is that it survives the process.
- A new key only when a genuinely new charge starts: the customer taps the card again, or someone consciously decides to retry as a different operation.

Two nuances worth checking while you're at it:

1. **The processor's key retention window.** Almost all of them expire idempotency keys (24 h is typical). A retry outside that window gets treated as a new charge even with an identical key, so deferred or re-queued retries need an explicit time limit.
2. **Which errors get retried.** With idempotency properly in place, retrying timeouts and 5xx is correct. A definitive rejection (insufficient funds, declined card) shouldn't be retried in a loop: it isn't a transport failure, and it only generates noise and possible blocking from the issuer.

**On the lack of tests**

The fact that there's no test on the retry is the reason this bug has been able to live in the code unnoticed: it doesn't fail on the happy path, only when the network misbehaves. Before calling the fix good, I'd add at least:

- The same key is sent on attempt 1 and on retry N (a direct assertion on the captured requests).
- A timeout on the first request followed by a successful retry → a single charge.
- A process restart between attempts → the persisted key is recovered, not a new one generated.
- Two genuinely different charges → different keys (so the fix doesn't overcorrect and block legitimate sales).

**In the meantime**

Until the fix is deployed, I wouldn't trust automatic retry in production. If you need an immediate mitigation, the cheapest option is to disable automatic retry and leave the retry in the cashier's hands after verifying the charge's status, or query the transaction's status at the processor before retrying. It's a worse experience, but a duplicate charge to a real customer costs quite a bit more than a manual retry.

And one check I'd do today, not once the fix is ready: if this has been in production for a while, there are probably already duplicate charges out there. I'd search the history for charges with the same amount, same card, and same terminal within a window of seconds, to know whether money needs to be refunded to anyone.
