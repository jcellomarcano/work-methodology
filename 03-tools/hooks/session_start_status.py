#!/usr/bin/env python3
"""SessionStart startup|resume|compact|clear: prints the current tree's
receipt state (Claude Code adds it as context) and leaves run-meta.json
with the session's wall clock. Prints nothing when RDD is off."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

HOOK = "session_start_status"


def main() -> int:
    inp = c.read_input()
    config = c.load_config()
    if not c.rdd_enabled(config):
        return 0
    c.write_run_meta(inp)
    repo = c.repo_root(inp)
    tree = c.current_tree(repo)
    receipt = c.receipt_for(tree)
    authority = (config.get("rdd") or {}).get("review_authority") or "kit"
    suffix = "" if authority == "kit" else " (this receipt is only the kit checkers' ledger; that lineage decides delivery)"
    lines = [f"[metodo] RDD {c.hook_mode(config, 'guard_gates')} mode; tree {tree[:12] if tree else 'no git repo'}",
             f"[metodo] review authority: {authority}{suffix}"]
    if receipt:
        risk = receipt.get("risk") or {}
        lines.append(f"[metodo] receipt: state={receipt.get('state')} verdict={receipt.get('verdict')} tier={risk.get('tier')} "
                     f"consent={risk.get('consent')} round={receipt.get('round_dir')}")
    else:
        lines.append("[metodo] receipt: none for this tree (receipt_start opens one; docs-only changes are exempt)")
    open_receipts = []
    try:
        for path in sorted(c.receipts_dir().glob("*.receipt.json")):
            other = json.loads(path.read_text(encoding="utf-8"))
            if other.get("state") != "finalized":
                open_receipts.append(f"{other['tree_sha'][:12]} ({other.get('state')}, {other.get('round_dir')})")
    except OSError:
        pass
    if open_receipts:
        lines.append("[metodo] open receipts: " + "; ".join(open_receipts[:5]))
    lines.append(f"[metodo] ledger: {c.session_dir(inp) / 'ledger.jsonl'}")
    print("\n".join(lines[:10]))
    c.ledger(inp, HOOK, "session-start", "log", "log", inp.get("source") or "", tree=tree,
             receipt=(receipt or {}).get("verdict") or ("open" if receipt else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
