Room is the right choice: it's where you keep state during a transaction that can be interrupted.

The flow is: Room records the attempt before calling the provider; the call happens; if it dies, Room already has the "in transit" state, and the next run sees it and retries. SharedPreferences isn't transactional and loses data. A custom write-ahead file duplicates what Room already does.

The architecture you need is a `PaymentInTransit` table with: unique ID, amount, timestamp, state (started/confirmed/failed/retry). When the process fails, the next run queries that table and finishes what was left hanging.

Room is the Android standard exactly for this: durability + reconstruction. Your hierarchy (Money > Recoverability) points to Room, not anywhere else.

The team is already paying Room's cost; don't multiply it with a custom file.

I need from you: is that unique ID generated locally (UUID) or does it come from the server, and does it arrive *after* the first attempt?
