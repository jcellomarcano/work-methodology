Room. And not for the team's convenience, but because it's the only one of the three that gives you atomic transactions + durability + a queryable history, which is exactly what your hierarchy calls for.

I'll rule out the other two quickly:

- **SharedPreferences**: no. `apply()` is asynchronous and can be lost on process death; `commit()` blocks and still rewrites the whole file with no per-key atomicity and no guaranteed ordering relative to the network call. It's also a blob of current state: you can't reconstruct *what happened*, only *how it ended up*. For money, that alone rules it out.
- **A custom WAL**: you'd be reimplementing SQLite's WAL, which is what Room already uses underneath, with less field testing, your own fsync, your own recovery from a truncated file, and your own format migrations. Months of work to end up worse off. It would only make sense if you had a requirement SQLite doesn't cover, and there isn't one here.

**The important part, though, isn't the store: it's the write protocol.** Choosing Room and still writing the state *after* calling the provider solves nothing. The design is:

1. **Before** calling the provider, insert an intent row with a client-generated idempotency key (UUID), amount, currency, state `STARTED`, timestamp. Wait for the transaction to commit.
2. Only then call the provider, **sending that same idempotency key**.
3. On receiving the response, transition to `CONFIRMED` / `REJECTED` with the provider's reference.

With that, if the process dies in the gap, on startup you find a row in `STARTED` and you know there's an operation with an unknown result. Which is the critical piece of information: **unknown is not failed**. Retrying without idempotency means charging twice, and assuming failure means losing a payment that went through. Both violate the top level of your hierarchy.

A couple of details that tend to bite:

- **An append-only transitions table**, not just current state. One row per state change, never a destructive `UPDATE` or `DELETE`. Your requirement to "reconstruct what happened" is literally an event log; the current-state table is a projection of that log.
- **`synchronous = FULL`** for these writes. Room runs WAL mode with `synchronous = NORMAL`, which is safe against process death but can lose the last commits on a power cut or kernel panic. If your threshold is "money," pay for the fsync; it's a few ms on an operation where the user is already waiting on a network call.
- **A reconciler in WorkManager**, not in the Activity lifecycle. On startup, with connectivity, sweep the non-terminal rows and query the real state from the provider by idempotency key. This is what turns "I know something happened" into "I know what happened."

And the question that needs resolving before the storage one: **does your provider support idempotency keys and status queries by that key?** If it doesn't, no local persistence decision saves you, you'll end up with orphaned intents you can't resolve against anyone, and that has to be negotiated or solved with your own intermediate endpoint before writing the first DAO.

One last framing point: the local database is an **intent journal**, not the ledger. The truth of the payment lives on the server. Room is there so you never lose sight of an operation and can ask about it, not so you can decide on your own that a charge went through fine.
