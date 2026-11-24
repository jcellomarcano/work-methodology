# clean-pass

repo_sha: `20c83b02fecccbd5d5ec48767ef6422abceaa21b`

4 rows flagged. No proposals: deciding what to do is the skill's job.

## By rule

| rule | rows |
|---|---|
| functions-over-50-file-level | 2 |
| lateinit-hotspot-top20 | 1 |
| var-hotspot-top20 | 1 |

## Flagged rows

| rule | file | detail |
|---|---|---|
| functions-over-50-file-level | booking/src/main/kotlin/com/shop/booking/BookingFlow.kt | 51-100:1, 101+:0 |
| functions-over-50-file-level | checkout/src/main/kotlin/com/shop/checkout/CartPricing.kt | 51-100:1, 101+:0 |
| lateinit-hotspot-top20 | checkout/src/main/kotlin/com/shop/checkout/CheckoutSession.kt | lateinit_count=1 |
| var-hotspot-top20 | checkout/src/main/kotlin/com/shop/checkout/CheckoutSession.kt | var_count=4 |

