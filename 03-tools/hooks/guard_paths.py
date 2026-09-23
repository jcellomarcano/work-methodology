#!/usr/bin/env python3
"""PreToolUse Edit|Write|MultiEdit. Absolute (always, even with RDD off): a
subagent never touches shared build files or .claude/**; the main session
gets `ask` on a build file. Non-absolute (warn|block mode): a subagent
outside its may_write or the open receipt's scope."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

HOOK = "guard_paths"


def main() -> int:
    inp = c.read_input()
    file_path = (inp.get("tool_input") or {}).get("file_path")
    if not file_path:
        return 0
    config = c.load_config()
    repo = c.repo_root(inp)
    rel = c.rel_path(file_path, repo)
    subagent = c.is_subagent(inp)

    hit = next((p for p in c.shared_build_patterns(config) if c.glob_match(rel, p)), None)
    if hit is not None:
        if subagent:
            c.ledger(inp, HOOK, "forbidden-path", "deny", "block", f"matches {hit}", path=rel)
            c.emit_pretool("deny", f"{rel} is a shared build file or .claude path: agents never edit it (methodology.md paragraph 4). Report it in your output instead.")
            return 0
        if ".claude" not in hit:
            c.ledger(inp, HOOK, "forbidden-path", "ask", "block", f"matches {hit}", path=rel)
            c.emit_pretool("ask", f"{rel} is a shared build file: owner gate.")
            return 0

    if not c.rdd_enabled(config) or not subagent:
        return 0

    contract = c.contract_for(inp.get("agent_type"), repo) or {}
    allow = [g for g in contract.get("may_write", []) if "<" not in g]
    receipt = c.receipt_for(c.current_tree(repo))
    if receipt is not None and receipt.get("state") != "finalized":
        allow += receipt.get("scope_globs") or []
    if not allow:
        return 0
    if any(c.glob_match(rel, g) for g in allow):
        return 0
    mode = c.hook_mode(config, HOOK)
    reason = f"{rel} is outside the role's may_write / receipt scope ({', '.join(allow)})"
    if mode == "block":
        c.ledger(inp, HOOK, "scope-outside", "deny", mode, reason, path=rel)
        c.emit_pretool("deny", reason + ". Stay inside the change card's scope boundary.")
    else:
        c.ledger(inp, HOOK, "scope-outside", "warn", mode, reason, path=rel)
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
