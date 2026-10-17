#!/usr/bin/env python3
"""Stop of the main session: runs the final reply through output_lint
(COM-01..18) and logs the FAILs in the ledger. Never blocks: it measures,
it is not a gate. Short replies (under 400 characters) are ignored."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

HOOK = "reply_lint"
MIN_CHARS = 400


def main() -> int:
    inp = c.read_input()
    if c.is_subagent(inp) or inp.get("stop_hook_active"):
        return 0
    text = inp.get("last_assistant_message") or ""
    if len(text) < MIN_CHARS:
        return 0
    config = c.load_config()
    if not c.rdd_enabled(config):
        return 0
    from lib import output_lint  # noqa: E402
    lint_config_path = c.TOOLS_ROOT / "config" / "output-lint.json"
    if not lint_config_path.exists():
        return 0
    lint_config = json.loads(lint_config_path.read_text(encoding="utf-8"))
    result = output_lint.check(text, lint_config, kind=None, audience="public")
    failed = sorted(r["id"] for r in result.get("rules", []) if r.get("status") == "FAIL")
    if failed:
        c.ledger(inp, HOOK, "reply-lint", "warn", c.hook_mode(config, HOOK), ", ".join(failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
