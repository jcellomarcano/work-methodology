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

The goal rule (00-principles/methodology.md paragraph 9) adds four checks.
ROLE names one specialised role: a general-purpose label fails, and with
--roster a role outside the roster fails unless the line carries an
explicit `model=`. OBJECTIVE is one sentence on one line. Every INPUTS line
opens with a path or an `engram:` reference, never prose. The whole text,
fields and anything around them, holds at most MAX_LINES non-empty lines
and MAX_CHARS characters, so a pasted file cannot ride with the brief.
SPECS and ALREADY READ accept the literal `none`; leaving them out fails.

Usage:
    lib/brief_check.py <brief.md> [--roster <dir with *.contract.json>]

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
MAX_LINES = 60
MAX_CHARS = 8000
NONE_ALLOWED = ("SPECS", "ALREADY READ")
GENERAL_PURPOSE = re.compile(
    r"^(general[- ]purpose|general|generalist|generic|assistant|agent|default|helper|any)( agent)?$", re.IGNORECASE)
MODEL = re.compile(r"\bmodel\s*=\s*\S+")
ROLE_NOTE = re.compile(r"\s+#|\s+-\s|,|\(")
SENTENCE_BREAK = re.compile(r"[.!?]\s+[A-Z]")
ABBREVIATION = re.compile(r"\b(e\.g|i\.e|vs|cf|approx)\.", re.IGNORECASE)
QUOTED = re.compile(r"(?<!\w)'[^']*'(?!\w)|\"[^\"]*\"|`[^`]*`")
BARE_FILES = ("none", "Makefile", "Dockerfile", "Jenkinsfile", "Procfile", "Gemfile", "Rakefile", "LICENSE",
              "README", "CHANGELOG", "AGENTS", "CODEOWNERS")
PATH_LIKE = re.compile(r"^(<|~|/|\$|\*|\.|engram:|https?://|[\w.@-]+/|[\w@-]+\.\w+)")


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


def roster_names(directory: str | Path) -> list[str]:
    """Role names of a roster directory: one `<role>.contract.json` each."""
    return sorted(p.name[: -len(".contract.json")] for p in Path(directory).glob("*.contract.json"))


def role_name(value: str) -> str:
    """The role before any `model=` declaration or note (`# ...`, ` - ...`, `, ...`, `(...)`)."""
    return ROLE_NOTE.split(MODEL.sub("", value).replace("`", ""), maxsplit=1)[0].strip()


def several_sentences(objective: str) -> bool:
    """A sentence break outside quotes and common abbreviations, or a second line."""
    return "\n" in objective or bool(SENTENCE_BREAK.search(ABBREVIATION.sub("", QUOTED.sub("", objective))))


def is_path(entry: str) -> bool:
    """The entry, with its quotes and its parenthesised note removed, opens
    with a path; a bare word is a path only when it is a known file name."""
    core = entry.split(" (")[0].strip()
    if len(core) > 1 and core[0] in "`'\"" and core[-1] == core[0]:
        core = core[1:-1].strip()
    return core in BARE_FILES or bool(PATH_LIKE.match(core))


def input_entries(value: str) -> list[str]:
    entries = []
    for line in value.splitlines():
        entry = line.strip()
        if entry.startswith("- "):
            entry = entry[2:].strip()
        if entry:
            entries.append(entry)
    return entries


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


def check(text: str, roster: list[str] | None = None) -> dict:
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
    specs = seen.get("SPECS", "")
    for entry in [] if specs.strip().lower() == "none" else spec_entries(specs):
        problems = spec_problems(entry)
        if problems:
            specs_invalid.append({"entry": entry, "problems": problems})
    budget = seen.get("BUDGET", "")
    budget_without_number = bool(budget.strip()) and not NUMBER.search(budget)
    role = role_name(seen.get("ROLE", ""))
    role_general_purpose = bool(GENERAL_PURPOSE.match(role))
    role_unknown = bool(roster is not None and role and not role.startswith("<") and not role_general_purpose
                        and role not in roster and not MODEL.search(seen.get("ROLE", "")))
    objective_not_one_sentence = several_sentences(seen.get("OBJECTIVE", ""))
    inputs_not_paths = [e for e in input_entries(seen.get("INPUTS", "")) if not is_path(e)]
    too_long = sum(1 for line in text.splitlines() if line.strip()) > MAX_LINES or len(text) > MAX_CHARS
    failed = (missing or empty or duplicate or out_of_order or specs_invalid or budget_without_number
              or role_general_purpose or role_unknown or objective_not_one_sentence or inputs_not_paths or too_long)
    return {
        "budget_without_number": budget_without_number,
        "duplicate": sorted(set(duplicate), key=FIELDS.index),
        "empty": empty,
        "fields": list(FIELDS),
        "inputs_not_paths": inputs_not_paths,
        "missing": missing,
        "objective_not_one_sentence": objective_not_one_sentence,
        "out_of_order": out_of_order,
        "role_general_purpose": role_general_purpose,
        "role_unknown": role_unknown,
        "specs_invalid": specs_invalid,
        "too_long": too_long,
        "verdict": "FAIL" if failed else "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("brief", help="path to the brief (Markdown)")
    parser.add_argument("--roster", help="directory of <role>.contract.json files; a ROLE outside it needs model=")
    args = parser.parse_args(argv)
    try:
        text = Path(args.brief).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(json.dumps({"brief": args.brief, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    result = check(text, roster=roster_names(args.roster) if args.roster else None)
    result["brief"] = args.brief
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
