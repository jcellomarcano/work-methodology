# Change card: apply the coupon before tax

**Why**: Tax is charged on the full price and the coupon is taken off afterwards, so a customer with a coupon pays tax on money they never paid. [Measured]
**For what**: Data integrity: the tax on a receipt is the tax on what was charged. [Inferred]
**What it risks**: A wrong total on every receipt that carries a coupon if the order of the two steps is wrong again. [Assumed]
**When**: With release 2.4, before the December campaign. [Assumed]
**How**: Take the coupon off the cart total first, then compute tax on the result; one function, called from checkout. [Inferred]
**How far**: Only the checkout total; no change to refunds or to stored orders. Undo by reverting the commit. [Inferred]
**How we'll know**: A cart of 100 with a 10 percent coupon is taxed on 90, on the terminal and in the receipt. [Inferred]
**Invariant**: INV-01
**Ticket**: PAY-231
