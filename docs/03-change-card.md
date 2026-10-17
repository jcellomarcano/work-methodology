# The Change Card

A short, structured note that explains a change before it's built. **No card, no PR.**

Use [04-templates/change-card.md](../04-templates/change-card.md) to start one.

## The 9 fields

| Field | Answers |
|---|---|
| Why | What problem or request is driving this? |
| For what | Which protected property does this gain or improve? |
| What it risks | Which protected property is put at risk by making this change? |
| When | What triggers this now — timing, deadline, dependency? |
| How | The approach, in a sentence or two |
| How far | Scope: what is in, what is explicitly NOT built, how to undo it |
| How we'll know | The evidence, metric, or test that proves it worked |
| Invariant | What must stay true, and the mechanism that guards it |
| Ticket | Link to the tracking issue |

## Example: idempotency key on order creation

| Field | Value |
|---|---|
| Why | Retried requests from an unreliable client are creating duplicate orders |
| For what | Data integrity (no duplicate orders) |
| What it risks | Performance (one extra lookup per request) |
| When | Triggered by a rise in duplicate-order support tickets this month |
| How | Require a client-supplied idempotency key; store it with the order; return the existing order on a repeated key |
| How far | Scope: order-creation endpoint only. NOT built: idempotency for order updates or cancellations. Rollback: remove the key check, endpoint falls back to prior behavior |
| How we'll know | Duplicate-order rate drops to zero in the next 2 weeks of production traffic; new test covers repeated-key behavior |
| Invariant | An order is never created twice for the same idempotency key — guarded by a unique constraint on the key column |
| Ticket | ORD-482 |

## Rule

If a PR doesn't link a filled change card, it doesn't get reviewed. This isn't bureaucracy — it's the fastest way to catch a bad idea before it becomes a bad diff.
