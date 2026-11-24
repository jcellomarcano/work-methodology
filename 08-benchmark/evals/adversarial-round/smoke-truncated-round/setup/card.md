# Change card: partial refunds

**Why**: Support refunds a whole order when one item of it comes back, and finance corrects about thirty of those by hand each week. [Measured]
**For what**: Data integrity: the refunded amount equals the price of the returned items. [Inferred]
**What it risks**: A refund larger than what the customer paid for the order. [Assumed]
**When**: Before the January returns peak. [Assumed]
**How**: Add a refund-lines table; the refund service sums the lines and rejects a total above the captured amount. [Inferred]
**How far**: Only the refund service and its table; no change to captures. Undo by reverting the commit and dropping the table. [Inferred]
**How we'll know**: A refund of one item of a three-item order leaves the other two charged in the ledger. [Inferred]
**Invariant**: INV-07
**Ticket**: PAY-340
