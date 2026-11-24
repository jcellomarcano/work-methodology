Yes: we can move the nightly export to the queue without losing a file.

A queue is like the ticket line at a deli: each export takes a number and waits its turn, so two never run at once. Unlike the deli, a ticket here is never thrown away when the shop closes: it is served the next morning.

What changes for your team:

- Exports start when the queue is free, not at a fixed hour.
- A failed export goes back to the end of the line.
- The dashboard shows the position of each export.
- Nothing changes in the files themselves.
- The dead-letter queue keeps what failed 3.

Next step: we switch one customer to the queue on Monday and watch it for a week.

## Technical detail
- The queue worker handles one export at a time [Inferred]
- Not tested: more than 40 exports waiting at once
