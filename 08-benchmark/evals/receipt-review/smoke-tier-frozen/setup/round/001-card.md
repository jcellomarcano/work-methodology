## Change Card

**Why**: Customers on slow connections lose their seat before the payment page loads; support logged 41 such tickets in October. [Measured]
**For what**: State correctness: a seat stays held while its buyer is still paying. [Inferred]
**What it risks**: A seat held five minutes longer is five minutes it cannot be sold to someone else. [Assumed]
**When**: Before the December schedule goes on sale. [Assumed]
**How**: Raise the default hold from 10 to 15 minutes in SeatHold. [Tested]
**How far**: Only the default of SeatHold; no change to the payment flow. Undo by reverting the commit. [Inferred]
**How we'll know**: Tickets tagged "seat lost while paying" drop in the two weeks after release. [Assumed]
**Invariant**: INV-02
**Ticket**: BOOK-118
