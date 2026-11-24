## Change Card

**Why**: The provider drops about one webhook in two hundred, and a dropped one leaves the order unpaid in our records. [Measured]
**For what**: Data integrity: every paid order is recorded as paid. [Inferred]
**What it risks**: A webhook applied twice would mark one order paid twice. [Assumed]
**When**: Before the November sales campaign starts. [Assumed]
**How**: Remember each webhook id and skip one already applied; retry a failed delivery with a growing delay. [Inferred]
**How far**: Only billing/RetryPolicy.kt and billing/WebhookHandler.kt; no change to refunds or exports. Undo by reverting the commit. [Inferred]
**How we'll know**: A replayed webhook id leaves one paid order in the records. [Tested]
**Invariant**: INV-04
**Ticket**: DEV-212
