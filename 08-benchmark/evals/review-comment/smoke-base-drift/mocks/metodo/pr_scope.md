{
  "base": "develop",
  "base_drift_files": [
    "billing/LegacyExport.kt"
  ],
  "commits": [
    {
      "sha": "cda73aa",
      "subject": "feat(billing): retry the payment webhook with backoff"
    }
  ],
  "head": "feature/retry-webhook",
  "merge_base": "76b7c321f6f2",
  "mixed_files": [],
  "pr_files": [
    {
      "added": 9,
      "path": "billing/RetryPolicy.kt",
      "removed": 1,
      "status": "M"
    },
    {
      "added": 12,
      "path": "billing/WebhookHandler.kt",
      "removed": 0,
      "status": "A"
    }
  ],
  "repo_dirty": false,
  "repo_sha": "cda73aa474aa",
  "summary": {
    "base_drift": 1,
    "commits": 1,
    "mixed": 0,
    "pr_files": 2
  },
  "tool_sha": "b5a7ef38128e"
}
