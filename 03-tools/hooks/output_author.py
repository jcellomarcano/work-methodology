#!/usr/bin/env python3
"""PostToolUse mcp__metodo__output_write. Records who wrote each round output
(T7, S2 of odd/tasks/delegation-context.md): one ledger line, kind
`output-authored`, decision `record`, reason
`author=<agent_type|main> role=<role> schema=<schema> sha256=<hex>`, path the
written file when it is found in the round dir.

The sha256 is the one of the bytes round_output.py writes (baseline.write_json:
sorted keys, indent 2, ensure_ascii False, one trailing newline), so it is
known from the tool input alone, on Claude Code and on pi. rdd_receipt.capture
looks the artifact's sha256 up in these lines and freezes the author in the
capture. A recorder: it never decides and never prints."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

HOOK = "output_author"
TOOL = "mcp__metodo__output_write"


def _role_and_schema(role: str, schema) -> tuple[str, str] | None:
    try:
        from lib import round_files
        role = round_files.normalize_role(role)
        return role, schema or round_files.ROLE_SCHEMA[role]
    except (ImportError, ValueError, KeyError):
        return None


def _written_file(round_dir, role: str, schema: str, sha: str, cwd) -> str | None:
    if not round_dir:
        return None
    base = Path(str(round_dir)).expanduser()
    if not base.is_absolute() and cwd:
        base = Path(str(cwd)) / base
    short = role[len("generic-"):] if role.startswith("generic-") else role
    try:
        candidates = sorted(base.glob(f"[0-9][0-9][0-9]-{short}-{schema}.json"), reverse=True)
        for path in candidates:
            if hashlib.sha256(path.read_bytes()).hexdigest() == sha:
                return path.resolve().as_posix()
    except OSError:
        return None
    return None


def main() -> int:
    inp = c.read_input()
    if inp.get("tool_name") != TOOL:
        return 0
    args = inp.get("tool_input") or {}
    document = args.get("document")
    if not isinstance(document, dict) or not isinstance(args.get("role"), str):
        return 0
    resolved = _role_and_schema(args["role"], args.get("schema"))
    if resolved is None:
        return 0
    role, schema = resolved
    text = json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    author = inp.get("agent_type") or ("subagent" if inp.get("agent_id") else "main")
    path = _written_file(args.get("round_dir"), role, schema, sha, inp.get("cwd"))
    c.ledger(inp, HOOK, "output-authored", "record", "log",
             f"author={author} role={role} schema={schema} sha256={sha}", path=path, tool=TOOL)
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
