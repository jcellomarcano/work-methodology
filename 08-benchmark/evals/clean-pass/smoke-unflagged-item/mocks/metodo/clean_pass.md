{
  "by_rule_count": {
    "functions-over-50-file-level": 2,
    "lateinit-hotspot-top20": 1,
    "var-hotspot-top20": 1
  },
  "flagged_items": [
    {
      "detail": "51-100:1, 101+:0",
      "file": "booking/src/main/kotlin/com/shop/booking/BookingFlow.kt",
      "rule": "functions-over-50-file-level"
    },
    {
      "detail": "51-100:1, 101+:0",
      "file": "checkout/src/main/kotlin/com/shop/checkout/CartPricing.kt",
      "rule": "functions-over-50-file-level"
    },
    {
      "detail": "lateinit_count=1",
      "file": "checkout/src/main/kotlin/com/shop/checkout/CheckoutSession.kt",
      "rule": "lateinit-hotspot-top20"
    },
    {
      "detail": "var_count=4",
      "file": "checkout/src/main/kotlin/com/shop/checkout/CheckoutSession.kt",
      "rule": "var-hotspot-top20"
    }
  ],
  "repo_dirty": false,
  "repo_sha": "20c83b02fecccbd5d5ec48767ef6422abceaa21b",
  "schema_version": "1.0.0",
  "tool_sha": "0392317d88a575d29ef1a878ce6e27a53dd3921d",
  "tool_versions": {
    "detekt": "1.23.8",
    "java": "21.0.12",
    "ktlint": "1.8.0",
    "pmd": "7.27.0",
    "python": "3.11.9"
  },
  "totals": {
    "flagged_items": 4
  }
}
