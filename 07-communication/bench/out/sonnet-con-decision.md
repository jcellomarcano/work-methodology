Room, with a payment-state table written in synchronous transactions.

- SharedPreferences isn't transactional: a half-finished write after a process kill leaves loose key-value pairs, not a reconstructible state.
- A custom WAL gives the same recoverability as Room if it's done well, but it duplicates what SQLite already solves and adds its own surface of bugs.
- Room is already on the team: zero learning curve and ACID transactions over SQLite, which is exactly what the recoverability constraint calls for.

| Option | Money | Recoverability | UX | Risk |
|---|---|---|---|---|
| SharedPreferences | Low | Low, not atomic | Quick to set up | High: inconsistent state if the process dies mid-write |
| Room | High, ACID transactions | High, SQLite WAL plus an explicit state machine | Zero curve, already known | Low |
| Custom WAL | High if done well | High but untested in this project | Has to be built and maintained | Medium: reinvents what Room already gives |

## Technical detail

- [Inferred] Minimal design: `payment_state` table with columns id, state (`STARTED` → `PROVIDER_CALLED` → `CONFIRMED`/`FAILED`), timestamp, and the provider's response payload.
- [Inferred] Write `PROVIDER_CALLED` in a transaction before calling the provider. On return, write the result in another transaction.
- [Inferred] If the process dies between those two writes, on restart there's an unclosed row in `PROVIDER_CALLED`. That row is the signal to re-query the provider, not to blindly retry.
- [Unknown] Whether the provider exposes an idempotency key or a status query endpoint.

I need from you: whether the provider gives an idempotency key or a status query, or whether that reconciliation has to be solved with a timeout and manual review.

Not tested: Room's actual behavior under a process kill on the target device. A process-kill test is worth doing before closing this out.
