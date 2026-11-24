{
  "run_id": "20261124141729-40698d",
  "tool": "metrics_delta",
  "log_path": "out/jobs/20261124141729-40698d/stdout.log",
  "status": "done",
  "exit_code": 2,
  "summary": {
    "tool_sha_after": "9ecc641b61d7b06bf76846e41990b6685258dd64",
    "tool_sha_before": "0392317d88a575d29ef1a878ce6e27a53dd3921d",
    "tool_versions_after": {
      "detekt": "1.23.8",
      "java": "21.0.12",
      "ktlint": "1.8.0",
      "pmd": "7.27.0",
      "python": "3.11.9"
    },
    "tool_versions_before": {
      "detekt": "1.23.8",
      "java": "21.0.12",
      "ktlint": "1.8.0",
      "pmd": "7.27.0",
      "python": "3.11.9"
    },
    "verdict": "VOID: tool drift"
  },
  "summary_path": "out/20c83b02fecccbd5d5ec48767ef6422abceaa21b/delta.json",
  "log_mtime_age_s": 0,
  "log_tail": [
    "== shape_metrics: /work/shop (sha 20c83b02fecccbd5d5ec48767ef6422abceaa21b) ==",
    "== duplication_cpd: /work/shop (sha 20c83b02fecccbd5d5ec48767ef6422abceaa21b) ==",
    "== delta vs a41d315937a3bb6ebecb4ab06015b6fbefc71831.json ==",
    "ERROR: baseline and current run come from different tool_sha values (or different tool_versions).",
    "  before: 0392317d88a575d29ef1a878ce6e27a53dd3921d {'detekt': '1.23.8', 'java': '21.0.12', 'ktlint': '1.8.0', 'pmd': '7.27.0', 'python': '3.11.9'}",
    "  now: 9ecc641b61d7b06bf76846e41990b6685258dd64 {'detekt': '1.23.8', 'java': '21.0.12', 'ktlint': '1.8.0', 'pmd': '7.27.0', 'python': '3.11.9'}",
    "  a delta between two versions of the tool itself is not a delta of the repo."
  ]
}
