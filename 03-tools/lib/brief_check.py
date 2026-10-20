#!/usr/bin/env python3
"""Checks a brief against the goal contract (04-templates/brief.md,
00-principles/agent-protocol.md section 1).

A field is a line that opens at column 0 with one of FIELDS and a colon;
its value is the rest of the line plus the indented lines under it. A
fenced block (the template's layout) is read the same way; any other
column-0 line ends the current field.

FAIL when a field is missing, empty, repeated or out of order; when a
SPECS entry is not a reference `<task-doc>.md#S<n>` (no S# id, no path, or
words beside the reference: the harness quotes the S# line from the file,
the brief never paraphrases it); when BUDGET carries no number.

Usage:
    lib/brief_check.py <brief.md>

Output: JSON on stdout, keys sorted. Exit 0 PASS, 1 FAIL, 2 unreadable
brief (JSON error on stderr).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FIELDS = ("ROLE", "OBJECTIVE", "SPECS", "ACCEPTANCE", "INPUTS", "SCOPE", "ALREADY READ",
          "CONSTRAINTS", "OUTPUT", "STOP", "BUDGET", "EVIDENCE")
HEADER = re.compile(r"^(" + "|".join(re.escape(f) for f in FIELDS) + r"):(.*)$")
SPEC_REF = re.compile(r"^[\w./<>-]+\.md#S\d+$")
SPEC_ID = re.compile(r"(?:^|[\s#(])S\d+\b")
SPEC_PATH = re.compile(r"[\w./<>-]+\.md\b")
NUMBER = re.compile(r"\d")


def parse(text: str) -> list[tuple[str, str]]:
    """(field, value) pairs in the order they appear."""
    fields: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        match = HEADER.match(line)
        if match:
            current = [match.group(2).strip()]
            fields.append((match.group(1), current))
        elif current is not None and line[:1] in (" ", "\t"):
            current.append(line.strip())
        else:
            current = None
    return [(name, "\n".join(v for v in value if v)) for name, value in fields]


def spec_entries(value: str) -> list[str]:
    entries = []
    for chunk in re.split(r"[,;\n]", value):
        entry = chunk.strip()
        if entry.startswith("- "):
            entry = entry[2:].strip()
        if entry:
            entries.append(entry)
    return entries


def spec_problems(entry: str) -> list[str]:
    if SPEC_REF.match(entry):
        return []
    problems = []
    if not SPEC_ID.search(entry):
        problems.append("no_id")
    if not SPEC_PATH.search(entry):
        problems.append("no_path")
    return problems or ["paraphrase"]


def check(text: str) -> dict:
    pairs = parse(text)
    seen: dict[str, str] = {}
    duplicate: list[str] = []
    out_of_order: list[str] = []
    highest = -1
    for name, value in pairs:
        if name in seen:
            duplicate.append(name)
            continue
        seen[name] = value
        rank = FIELDS.index(name)
        if rank < highest:
            out_of_order.append(name)
        highest = max(highest, rank)
    missing = [f for f in FIELDS if f not in seen]
    empty = [f for f in FIELDS if f in seen and not seen[f].strip()]
    specs_invalid = []
    for entry in spec_entries(seen.get("SPECS", "")):
        problems = spec_problems(entry)
        if problems:
            specs_invalid.append({"entry": entry, "problems": problems})
    budget = seen.get("BUDGET", "")
    budget_without_number = bool(budget.strip()) and not NUMBER.search(budget)
    failed = missing or empty or duplicate or out_of_order or specs_invalid or budget_without_number
    return {
        "budget_without_number": budget_without_number,
        "duplicate": sorted(set(duplicate), key=FIELDS.index),
        "empty": empty,
        "fields": list(FIELDS),
        "missing": missing,
        "out_of_order": out_of_order,
        "specs_invalid": specs_invalid,
        "verdict": "FAIL" if failed else "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("brief", help="path to the brief (Markdown)")
    args = parser.parse_args(argv)
    try:
        text = Path(args.brief).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(json.dumps({"brief": args.brief, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    result = check(text)
    result["brief"] = args.brief
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
