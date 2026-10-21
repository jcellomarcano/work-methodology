#!/usr/bin/env python3
"""PostToolUse mcp__metodo__output_write and Edit|Write|MultiEdit. Records who wrote each round output
(T7, S2 of odd/tasks/delegation-context.md): one ledger line, kind
`output-authored`, decision `record`, reason
`author=<agent_type|main> role=<role> schema=<schema> sha256=<hex>`, path the
written file when it is found in the round dir.

The sha256 is the one of the bytes round_output.py writes (baseline.write_json:
sorted keys, indent 2, ensure_ascii False, one trailing newline), so it is
known from the tool input alone, on Claude Code and on pi. rdd_receipt.capture
looks the artifact's sha256 up in these lines and freezes the author in the
capture. A recorder: it never decides and never prints.

T18 (B-005/A-006): a file tool also writes round outputs. On Edit, Write or
MultiEdit the line is written when the file lands in a round dir: the
round_dir of a receipt not yet finalized ($METODO_RDD_DIR), or a file named
like a round_output.py output (NNN-<role>-<schema>.json). The sha256 is the
one of the bytes on disk after the call; role and schema come from that name,
else `any` (rdd_receipt.author_of matches `any` to every role). The author
is main when the call has no agent_id/agent_type, else the subagent's role
(`subagent` when only the agent_id is known)."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

HOOK = "output_author"
TOOL = "mcp__metodo__output_write"
FILE_TOOLS = ("Edit", "Write", "MultiEdit")
ANY = "any"
OUTPUT_NAME_RE = re.compile(r"^\d{3}-([a-z0-9-]+)\.json$")


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


def _author(inp: dict) -> str:
    return inp.get("agent_type") or ("subagent" if inp.get("agent_id") else "main")


def _named_output(name: str) -> tuple[str, str] | None:
    """(role, schema) when the file name is NNN-<short role>-<schema>.json."""
    match = OUTPUT_NAME_RE.match(name)
    if not match:
        return None
    try:
        from lib import round_files
    except ImportError:
        return None
    for role, schema in round_files.ROLE_SCHEMA.items():
        if match.group(1) == f"{round_files.short_role(role)}-{schema}":
            return role, schema
    return None


def _open_round_dirs() -> list[Path]:
    dirs = []
    for receipt in sorted(c.receipts_dir().glob("*.receipt.json")):
        try:
            data = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("state") != "finalized" and data.get("round_dir"):
            base = Path(str(data["round_dir"])).expanduser()
            if base.is_absolute():
                dirs.append(base.resolve())
    return dirs


def _file_tool(inp: dict) -> int:
    file_path = (inp.get("tool_input") or {}).get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return 0
    path = Path(file_path).expanduser()
    if not path.is_absolute() and inp.get("cwd"):
        path = Path(str(inp["cwd"])) / path
    path = path.resolve()
    named = _named_output(path.name)
    if named is None and not any(path.is_relative_to(d) for d in _open_round_dirs()):
        return 0
    try:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return 0
    role, schema = named or (ANY, ANY)
    c.ledger(inp, HOOK, "output-authored", "record", "log",
             f"author={_author(inp)} role={role} schema={schema} sha256={sha}", path=path.as_posix(),
             tool=inp.get("tool_name"))
    return 0


def main() -> int:
    inp = c.read_input()
    if inp.get("tool_name") in FILE_TOOLS:
        return _file_tool(inp)
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
    author = _author(inp)
    path = _written_file(args.get("round_dir"), role, schema, sha, inp.get("cwd"))
    c.ledger(inp, HOOK, "output-authored", "record", "log",
             f"author={author} role={role} schema={schema} sha256={sha}", path=path, tool=TOOL)
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
