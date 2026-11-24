{
  "dep_summary": {
    "adapter_law_candidates_total": 0,
    "cycle_candidates": {
      "app-framework->app-ui": 0,
      "app-ui->app-framework": 0
    },
    "violations_total": 0
  },
  "hotspots": [
    {
      "path": "booking/src/main/kotlin/com/shop/booking/BookingFlow.kt",
      "touches": 2
    },
    {
      "path": "checkout/src/main/kotlin/com/shop/checkout/Cart.kt",
      "touches": 2
    },
    {
      "path": "checkout/src/main/kotlin/com/shop/checkout/CartPricing.kt",
      "touches": 2
    },
    {
      "path": "checkout/src/main/kotlin/com/shop/checkout/CheckoutSession.kt",
      "touches": 2
    },
    {
      "path": "gradle/libs.versions.toml",
      "touches": 2
    },
    {
      "path": "app/src/main/kotlin/com/shop/app/Main.kt",
      "touches": 1
    },
    {
      "path": "billing-legacy/src/main/java/com/shop/billing/Invoice.java",
      "touches": 1
    },
    {
      "path": "checkout/src/main/kotlin/com/shop/checkout/Coupons.kt",
      "touches": 1
    },
    {
      "path": "settings.gradle",
      "touches": 1
    }
  ],
  "merge_conflict_simulation": {
    "available": true,
    "conflicted_paths": [
      "checkout/src/main/kotlin/com/shop/checkout/Cart.kt",
      "gradle/libs.versions.toml"
    ],
    "target_branch": "origin/develop"
  },
  "repo_dirty": false,
  "repo_sha": "20c83b02fecccbd5d5ec48767ef6422abceaa21b",
  "schema_version": "1.0.0",
  "shape_summary": {
    "files_count": 6,
    "files_over_500": 0,
    "fun_count": 9,
    "loc": 181
  },
  "tool_sha": "0392317d88a575d29ef1a878ce6e27a53dd3921d",
  "tool_versions": {
    "detekt": "1.23.8",
    "java": "21.0.12",
    "ktlint": "1.8.0",
    "pmd": "7.27.0",
    "python": "3.11.9"
  }
}
