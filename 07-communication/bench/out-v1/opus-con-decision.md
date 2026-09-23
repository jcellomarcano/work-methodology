Room, writing the payment intent before calling the provider. I'm ruling out SharedPreferences and a custom write-ahead file.

- SharedPreferences doesn't work for money: it stores key-value pairs with no transaction and no history, and `apply()` writes in the background, so process death can lose the last change.
- A custom file does solve the problem, but it forces you to write durability yourself: atomic writes, record ordering, retries, migrations. Room already gets that from SQLite underneath.
- Room is a write-ahead log if you use it that way: a row with state `STARTED` and its idempotency key commits to disk before the network request. On startup, any row still in `STARTED` is a payment with an unknown outcome and gets queried against the provider.
- Think of it like the cashier's notebook: write down the charge before putting the money in the till. The notebook is the payments table; the till, the provider. Where it breaks: if the notebook only gets saved at the end of the shift, it's useless, which is why the exact moment SQLite commits the row matters.
- None of this works without an idempotency key per attempt, generated and stored on the device. That's what stops a double charge on retry.

| Option | Main risk |
|---|---|
| SharedPreferences | Silent loss of the last state and no trail to reconstruct what happened |
| Room (recommended) | A false sense of durability if you write the row after the call, or outside a transaction |
| Custom write-ahead file | New durability code, untested by years of use, sitting on the money path |

I need from you: confirmation that the provider accepts an idempotency key and that it exposes a status query by that key. Without that, recovery after a failure isn't reconstructible, and it changes the decision.

## Technical detail

- [Inferred] `payment_attempt` table with: `idempotency_key` (unique), `state` in `CREATED -> SENT -> CONFIRMED | REJECTED | UNKNOWN`, amount in cents, `updated_at`. Forward-only transitions, never deleted, so the trail stays.
- [Inferred] Mandatory order: the Room transaction that inserts `SENT` commits first, then the network call. If you flip the order, Room stops being write-ahead and you're back to the SharedPreferences problem.
- [Assumed] With `journal_mode=WAL` and `synchronous=NORMAL` (Room's defaults) a committed transaction survives process death, but not necessarily a power cut. That needs `synchronous=FULL`, at the cost of write latency.
- [Inferred] Reconciliation runs in a `WorkManager` with exponential backoff: on app startup and after network recovers, take the rows in `SENT` and ask the provider about their key.
- [Unknown] How much `synchronous=FULL` costs on your device fleet. Measure it with a write benchmark on the low-end percentile before locking it in.

Not tested: I didn't run any process-kill test or consult SQLite's or Room's documentation in this session. The claims about `synchronous` and Room's defaults need verifying against your version's documentation before closing the design.
