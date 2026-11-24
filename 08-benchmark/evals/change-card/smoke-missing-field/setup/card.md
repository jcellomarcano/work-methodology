# Change card: retry the payment webhook

**Why**: The provider drops about one webhook in two hundred, and a dropped one leaves the order unpaid in our records. [Measured]
**For what**: Data integrity: every paid order is recorded as paid. [Inferred]
**When**: Before the November sales campaign starts. [Assumed]
**How**: Store the webhook id and skip an id that was already applied; retry three times with backoff. [Inferred]
**How far**: Only the payment webhook handler; no change to refunds. Undo by reverting the commit. [Inferred]
**Invariant**: INV-04
**Ticket**: PAY-212
