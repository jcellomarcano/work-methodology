#!/usr/bin/env python3
"""PreToolUse with no matcher. Main session: exits immediately. Subagent:
counts its calls in out/hooks/<session>/budget-<agent_type>-<agent_id>.count
and, once its contract's max_tool_calls is exceeded, denies with the
instruction to close with truncated:true. Absolute: always in block."""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

HOOK = "budget"


def main() -> int:
    inp = c.read_input()
    if not c.is_subagent(inp):
        return 0
    agent_type = inp.get("agent_type") or "unknown"
    agent_id = inp.get("agent_id") or "unknown"
    contract = c.contract_for(agent_type, c.repo_root(inp)) or {}
    cap = contract.get("max_tool_calls")
    if not cap:
        return 0
    sdir = c.session_dir(inp)
    sdir.mkdir(parents=True, exist_ok=True)
    counter = sdir / f"budget-{agent_type}-{agent_id}.count"
    try:
        count = int(counter.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        count = 0
    count += 1
    counter.write_text(f"{count}\n", encoding="utf-8")
    if count > int(cap):
        c.ledger(inp, HOOK, "budget-deny", "deny", "block", f"{count} > {cap}")
        c.emit_pretool("deny", f"budget exhausted ({cap} tool calls): stop now and emit your JSON with truncated:true and not_covered.")
    elif count == math.ceil(0.8 * int(cap)):
        c.ledger(inp, HOOK, "budget-warn", "warn", "block", f"{count} of {cap}")
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
