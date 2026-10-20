#!/usr/bin/env python3
"""SessionStart startup|resume|compact|clear: prints the current tree's
receipt state (Claude Code adds it as context) and leaves run-meta.json
with the session's wall clock. Prints nothing when RDD is off.

On compact and resume it also restores a goal anchor (context-method.md
section 4.3): the active task document, its open task ids with their S#,
and the last receipt state for the current tree, at most 120 tokens
(ceil(chars / 4)), sent as SessionStart additionalContext. The active
document is config memory.active_task_doc when set, else the latest-modified
odd/tasks/*.md whose `## Tasks` table has a row not marked done. Nothing
outside the repo is read."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

HOOK = "session_start_status"
ANCHOR_SOURCES = ("compact", "resume")
ANCHOR_MAX_TOKENS = 120
TASK_DOC_MAX_BYTES = 256 * 1024


def _inside(path: Path, repo: Path) -> Path | None:
    try:
        resolved = path.resolve()
        resolved.relative_to(repo.resolve())
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def _cells(line: str) -> list[str]:
    """Splits a table row on `|`, except an escaped `\\|` or one inside a
    backtick code span (task docs write `a|b` in Work cells)."""
    cells, current, in_code, i = [], [], False, 0
    body = line.strip()
    while i < len(body):
        char = body[i]
        if char == "\\" and body[i + 1:i + 2] == "|":
            current.append("|")
            i += 2
            continue
        if char == "`":
            in_code = not in_code
        if char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        i += 1
    cells.append("".join(current).strip())
    if body.startswith("|"):
        cells = cells[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        cells = cells[:-1]
    return cells


def open_tasks(text: str) -> list[tuple[str, str]]:
    """(id, specs) for every row of the `## Tasks` table whose status does not
    start with `done`, in document order."""
    rows: list[tuple[str, str]] = []
    in_section = False
    header: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            if in_section:
                break
            in_section = line[3:].strip().lower().startswith("tasks")
            continue
        if not in_section:
            continue
        if not line.lstrip().startswith("|"):
            if header is not None and line.strip():
                break
            continue
        cells = _cells(line)
        if header is None:
            header = [cell.lower() for cell in cells]
            continue
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells if cell):
            continue
        try:
            id_col = header.index("id")
            status_col = header.index("status")
        except ValueError:
            return []
        spec_col = next((i for i, name in enumerate(header) if name.startswith("spec")), None)
        if len(cells) <= max(id_col, status_col) or not cells[id_col]:
            continue
        if cells[status_col].lower().startswith("done"):
            continue
        specs = " ".join(cells[spec_col].split()) if spec_col is not None and spec_col < len(cells) else ""
        rows.append((cells[id_col], specs))
    return rows


def _read_doc(path: Path) -> str:
    try:
        if path.stat().st_size > TASK_DOC_MAX_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def active_task_doc(repo: Path, config: dict) -> tuple[str, list[tuple[str, str]]] | None:
    configured = str((config.get("memory") or {}).get("active_task_doc") or "").strip()
    if configured and not Path(configured).is_absolute():
        path = _inside(repo / configured, repo)
        if path is not None:
            return path.relative_to(repo.resolve()).as_posix(), open_tasks(_read_doc(path))
    candidates = []
    for doc in (repo / "odd" / "tasks").glob("*.md"):
        path = _inside(doc, repo)
        if path is not None:
            candidates.append((-path.stat().st_mtime_ns, doc.name, path))
    for _, _, path in sorted(candidates):
        rows = open_tasks(_read_doc(path))
        if rows:
            return path.relative_to(repo.resolve()).as_posix(), rows
    return None


def goal_anchor(repo: Path | None, config: dict, tree: str | None, receipt: dict | None) -> str | None:
    if repo is None:
        return None
    found = active_task_doc(repo, config)
    if not found or not found[1]:
        return None
    doc, rows = found
    short = tree[:12] if tree else "none"
    if receipt:
        last = f"state={receipt.get('state')} verdict={receipt.get('verdict')} tree={short}"
    else:
        last = f"none for tree {short}"
    entries = [f"{task_id} ({specs})" if specs else task_id for task_id, specs in rows]
    limit = ANCHOR_MAX_TOKENS * 4
    for kept in range(len(entries), 0, -1):
        listed = ", ".join(entries[:kept]) + (f", +{len(entries) - kept} more" if kept < len(entries) else "")
        text = f"[metodo] goal anchor: {doc}; open: {listed}; last receipt: {last}"
        if len(text) <= limit:
            return text
    return text[:limit - 1] + "\u2026"


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
    anchor = goal_anchor(repo, config, tree, receipt) if inp.get("source") in ANCHOR_SOURCES else None
    if anchor:
        context = "\n".join(lines[:9] + [anchor])
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}},
                         ensure_ascii=False))
    else:
        print("\n".join(lines[:10]))
    c.ledger(inp, HOOK, "session-start", "log", "log", inp.get("source") or "", tree=tree,
             receipt=(receipt or {}).get("verdict") or ("open" if receipt else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
