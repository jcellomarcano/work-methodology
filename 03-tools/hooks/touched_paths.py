#!/usr/bin/env python3
"""PostToolUse Edit|Write|MultiEdit: logs the touched path and agent in
out/hooks/<session>/touched.jsonl, test_sectors's input for the loop."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402


def main() -> int:
    inp = c.read_input()
    file_path = (inp.get("tool_input") or {}).get("file_path")
    if not file_path or not c.rdd_enabled(c.load_config()):
        return 0
    rel = c.rel_path(file_path, c.repo_root(inp))
    sdir = c.session_dir(inp)
    sdir.mkdir(parents=True, exist_ok=True)
    with (sdir / "touched.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"path": rel, "agent_type": inp.get("agent_type")}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
