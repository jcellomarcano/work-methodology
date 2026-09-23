Storing payment state in Room, with an intent record before calling the provider and its confirmation afterward, covers all four constraints without adding a new tool.

- Room already persists to SQLite, which writes in write-ahead-log mode: the row survives if the process dies between the call and the confirmation.
- A table with states (`PENDING` → `SENT` → `CONFIRMED`/`FAILED`) reconstructs what happened when the app reopens, with a timestamp on every transition.
- The team already uses Room: it adds no new piece to the money critical path, which sits at the top of the hierarchy.
- SharedPreferences offers neither transactions nor querying by state: it's fine for simple flags, not for reconstructing a sequence of payment events.
- A custom WAL gives the same durability SQLite already provides, but with new code that has to be tested and maintained; that risk isn't justified when Room already solves it.

| Option | Risk |
|---|---|
| Room (intent + confirmation) | Low: reuses proven infrastructure, atomic transactions |
| SharedPreferences | High: no atomicity or history, doesn't reconstruct the sequence |
| Custom WAL | Medium-high: duplicates what SQLite already gives, more bug surface on the money path |

I need from you: confirm the table's states (`PENDING`, `SENT`, `CONFIRMED`, `FAILED`, others) and whether reconciliation on app reopen runs on its own or needs user action.

## Technical detail

- [Inferred] SQLite, Room's engine, supports WAL mode from API 16 onward; a row write is atomic per transaction.
- [Assumed] The call to the provider isn't idempotent by default; it's assumed an operation id is needed to reconcile after a reconnect.
- Not tested: how the specific payment provider behaves on a retry after a crash (whether it exposes an idempotency key).
