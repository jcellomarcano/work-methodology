Room, with a payment-attempt table you write before calling the provider and update when it returns. Neither SharedPreferences nor a custom file.

- The write-ahead you're looking for, you already have: Room sits on SQLite, and a confirmed transaction survives process death. A custom file reimplements that and adds code you have to maintain.
- To reconstruct what happened you need history, not a field that gets overwritten. Store one row per state transition, and never delete it.
- Generate the idempotency key on the client and save it before calling the provider. Without it, a retry after a crash can charge the customer twice. That's irreversible.
- On startup, any attempt left in `started` or `sent` gets queried against the provider. The provider holds the real state, not your app.
- Analogy: you write the order on the ticket before taking it to the kitchen. The ticket is the row in Room, the kitchen is the provider. It breaks here: the kitchen may have made the dish even if the ticket never got marked, which is why you have to ask the kitchen when you reopen.

| Option | What it gives | Risk |
|---|---|---|
| Room (recommended) | Transactions, queries, migrations, history in a separate table; the team already uses it | Badly written migrations can lose rows; they need testing |
| SharedPreferences | Simple, zero new code | `apply()` writes to disk asynchronously and there's no transaction spanning keys; payment state can be lost right at the crash |
| Custom write-ahead file | Full control of the format | Duplicates what SQLite already does well; atomic writes, fsync, and partial corruption become your problem |

I need from you: confirm two things about the provider. First, whether it accepts an idempotency key per attempt. Second, whether it exposes a status query by that key. If either answer is no, recovery isn't reliable and the design changes.

Not tested: I haven't seen your Room schema or the provider's contract. None of this has been run.

## Technical detail

- Proposed schema: `payment_attempt` table with `idempotency_key` as primary key, `state` (`started`, `sent`, `confirmed`, `failed`, `unknown`), `provider_ref`, `amount_minor` (amount in the minor unit, cents), `created_at`, `updated_at`. An insert-only `payment_event` table, one row per transition, for reconstruction. [Assumed] I don't know your current entities.
- Write order: 1) insert `started` in a transaction and wait for it to commit; 2) call the provider; 3) update to `sent` or the final state. If the process dies between 2 and 3, the row stays at `started` or `sent` and reconciliation on startup decides. [Inferred] from SQLite's transactional behavior.
- Durability: Room delegates to SQLite, which commits the transaction to disk before returning. Process death does not undo an already-committed transaction; a power cut is a different case. [Inferred], not measured in your app.
- SharedPreferences: `apply()` writes to disk asynchronously and `commit()` is synchronous, but there is no transaction spanning multiple keys, nor history. [Inferred] from Android's documentation; I don't have the literal quote in front of me, it's worth verifying before closing the decision.
- Hierarchy applied: Money rules, so the idempotency key and reconciliation come before any UX improvement. Payment state and Recoverability are covered by the event table. UX here is showing `verifying` while reconciliation runs, instead of assuming success. [Assumed] this is my reading of your hierarchy, tell me if I've ordered it wrong.
- Inconclusive point: if the provider doesn't return the same reference for a retry with the same key, you can't tell a single charge from a double charge on the client side. Find out with a test in their sandbox: same `idempotency_key`, two calls, compare responses.
