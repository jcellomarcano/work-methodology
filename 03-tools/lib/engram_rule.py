#!/usr/bin/env python3
"""The Engram read/write rule: when a session may read persistent memory,
how much, and what it may save (odd/research/context/engram.md section 5,
owner decision D4 in odd/tasks/context-optimization.md L6).

D4: memory stays on with a read rule. Only the main session reads, only at
start, resume or right after a compaction, under a byte cap; a subagent
never touches Engram (the parent forwards what is relevant). The kill
switch is METODO_MEMORY=off or `memory.enabled: false` in project.json.

`decide` is pure and deterministic: no I/O, first matching row wins.

| # | Condition                | Reads                                         | Writes                    |
|---|--------------------------|-----------------------------------------------|---------------------------|
| 1 | kill switch or no binary | off                                           | off                       |
| 2 | caller is a subagent     | off                                           | off                       |
| 3 | sensitive task or repo   | 1 search, explicit project only               | off                       |
| 4 | project unresolved       | 1 search, explicit project only               | off                       |
| 5 | just compacted           | mem_context(compact, 4096 bytes) once         | session summary           |
| 6 | resume                   | task doc, mem_context 4096, <= 2 searches x 5 | decision, handoff         |
| 7 | new multi-session task   | 1 search x 5 before exploring                 | decision, handoff         |
| 8 | trivial task             | off                                           | non-obvious bugfix/decision |
| 9 | otherwise                | 1 search x 5 only if the prompt names earlier work | decision             |

`should_disable` is the auto-off check: after at least 20 sessions with a
recall-used rate under 0.2, the default flips to `memory.enabled: false`.
The stats come in as a dict; nothing is measured here.

Usage:
    lib/engram_rule.py --phase start|resume|compact|task [--caller main|subagent]
        [--sensitive] [--trivial] [--multi-session] [--mentions-earlier]
        [--project-unresolved]

The CLI reads METODO_MEMORY, `memory.enabled` from config/project.json
(METODO_PROJECT_CONFIG overrides the path) and whether `engram` is on PATH;
it never runs the binary. Output: JSON on stdout, keys sorted. Exit 0, or 2
on a bad argument.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import engram_bridge  # noqa: E402

PHASES = ("start", "resume", "compact", "task")
CALLERS = ("main", "subagent")
KINDS = ("trivial", "standard", "multi-session")
CONTEXT_MAX_BYTES = 4096
SEARCH_LIMIT = 5
RESUME_SEARCHES = 2
DISABLE_MIN_SESSIONS = 20
DISABLE_MIN_RATE = 0.2

# Missing facts are never assumed true: no binary and no enabled flag means off.
DEFAULTS = {"memory_env": "", "memory_enabled": False, "binary": False, "caller": "main",
            "sensitive": False, "project_resolved": False, "phase": "start",
            "kind": "standard", "mentions_earlier": False}
EXPLICIT = "explicit project only, never all_projects"


def _result(rule: int, reasons: list[str], reads: list[str] | None = None, writes: list[str] | None = None,
            max_bytes: int = 0, searches: int = 0) -> dict:
    return {"rule": rule, "reasons": reasons, "reads": list(reads or []), "writes": list(writes or []),
            "max_bytes": max_bytes, "searches": searches, "results": SEARCH_LIMIT if searches else 0}


def _check(name: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)}, got {value!r}")


def decide(inputs: dict) -> dict:
    """The first matching row of the table in the module docstring."""
    facts = {**DEFAULTS, **(inputs or {})}
    phase, caller, kind = facts["phase"], facts["caller"], facts["kind"]
    _check("phase", phase, PHASES)
    _check("caller", caller, CALLERS)
    _check("kind", kind, KINDS)

    if str(facts["memory_env"] or "").lower() == "off":
        return _result(1, ["kill switch: METODO_MEMORY=off"])
    if not facts["memory_enabled"]:
        return _result(1, ["kill switch: memory.enabled is false"])
    if not facts["binary"]:
        return _result(1, ["no engram binary on PATH"])
    if caller == "subagent":
        return _result(2, ["subagents never use Engram; the parent forwards what is relevant"])
    if facts["sensitive"]:
        return _result(3, ["sensitive task or repo: no saves", EXPLICIT], ["mem_search"], searches=1)
    if not facts["project_resolved"]:
        return _result(4, ["project unresolved: no saves until it resolves", EXPLICIT], ["mem_search"], searches=1)
    if phase == "compact":
        return _result(5, ["just compacted: compact context once"], ["mem_context"], ["session_summary"],
                       max_bytes=CONTEXT_MAX_BYTES)
    if phase == "resume":
        return _result(6, ["resume: task doc first, then compact context and targeted searches"],
                       ["task_doc", "mem_context", "mem_search"], ["decision", "handoff"],
                       max_bytes=CONTEXT_MAX_BYTES, searches=RESUME_SEARCHES)
    if kind == "multi-session":
        return _result(7, ["new multi-session task: one search on the feature name before exploring"],
                       ["mem_search"], ["decision", "handoff"], searches=1)
    if kind == "trivial":
        return _result(8, ["trivial task: no reads"], writes=["non_obvious_bugfix", "non_obvious_decision"])
    if facts["mentions_earlier"]:
        return _result(9, ["the prompt names earlier work: one search"], ["mem_search"], ["decision"], searches=1)
    return _result(9, ["no earlier work named: no reads"], writes=["decision"])


def should_disable(stats: dict) -> bool:
    """True when memory has had its chance and was not used: at least
    DISABLE_MIN_SESSIONS sessions and a recall-used rate below DISABLE_MIN_RATE.
    The rate comes as `recall_used_rate`, or from `recalls_used / recalls`
    (no recall at all counts as 0.0). No rate and no counts: never disable."""
    stats = stats or {}
    if int(stats.get("sessions") or 0) < DISABLE_MIN_SESSIONS:
        return False
    if stats.get("recall_used_rate") is not None:
        rate = float(stats["recall_used_rate"])
    elif "recalls" in stats:
        recalls = int(stats.get("recalls") or 0)
        rate = int(stats.get("recalls_used") or 0) / recalls if recalls else 0.0
    else:
        return False
    return rate < DISABLE_MIN_RATE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Engram read/write rule (engram.md section 5, D4)")
    parser.add_argument("--phase", required=True, choices=PHASES)
    parser.add_argument("--caller", default="main", choices=CALLERS)
    parser.add_argument("--sensitive", action="store_true")
    parser.add_argument("--project-unresolved", action="store_true")
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument("--trivial", action="store_true")
    kind.add_argument("--multi-session", action="store_true")
    parser.add_argument("--mentions-earlier", action="store_true")
    args = parser.parse_args(argv)

    config = engram_bridge.load_config()
    inputs = {
        "memory_env": os.environ.get("METODO_MEMORY", ""),
        "memory_enabled": bool((config.get("memory") or {}).get("enabled")),
        "binary": bool(shutil.which("engram")),
        "caller": args.caller,
        "sensitive": args.sensitive,
        "project_resolved": not args.project_unresolved,
        "phase": args.phase,
        "kind": "trivial" if args.trivial else "multi-session" if args.multi_session else "standard",
        "mentions_earlier": args.mentions_earlier,
    }
    print(json.dumps(decide(inputs), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
