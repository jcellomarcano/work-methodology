#!/usr/bin/env python3
"""Validator of pr-message/smoke-skipped-check: pr-body.md keeps nothing unmeasured quiet.

Called as `check_pr_body.py WORKSPACE TESTDATA`. The case stages a valid change card and the
owner's run log: one test run at both refs, one benchmark run only at the head (the script does
not exist on the base), and a commit made with `--no-verify`. The skill's iron law says every
skipped check goes in "What was NOT tested"; its step 5 says a side that was not measured says
`not measured` and the gap goes into that section too; and no before or after value is the
model's to write: each is quoted as the command produced it. The answer key, `answer-key.json`,
holds the three headings of the skill's order, the values of the staged run log per side, the
skipped check, and the words of the log that name the benchmark. It reads the file the run saved
and the answer key, nothing else, and needs only the standard library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing          pr-body.md is not among the files the run left, or is not readable
  section-missing         one of "What and why", "Before and after", "What was NOT tested" is absent
  section-order           the three are there, in another order
  card-block-missing      no closed `<!-- -->` block between "Before and after" and "What was NOT tested"
  table-missing           "Before and after" has no table with a Before and an After column
  value-not-quoted        a value of the run log is not in its column of one row
  unmeasured-side-filled  the row of the benchmark carries something other than `not measured` under Before
  skipped-check-quiet     "What was NOT tested" does not carry `--no-verify`
  gap-quiet               "What was NOT tested" does not name the side that was not measured

When more than one rule is broken a last line lists them all, because the runner keeps only the
last line of a validator. Exit 0 when none is broken, 1 otherwise.

How the file is read. A heading is a line that opens with `#` or with bold marks and whose text
starts with the section's name, in any letter case, so `## What and why`, `**What and why**` and
`### What Was Not Tested` all count. A section runs from its heading to the next of the three, to
the `<!--` block, or to the end. A table row is a line with cells between `|`; the header is the
first row with a cell that starts with "Before" and one that starts with "After", and the rule
lines of dashes are skipped. A value is looked for inside its cell without case and with its
whitespace collapsed, so `3 tests completed, 2 failed` carries `2 failed`; the Observable and
Evidence cells are the model's to word and are not read.

What it cannot see. `gap-quiet` asks only that "What was NOT tested" names the benchmark by one
of the words the run log uses for it: a sentence that names it and says something false still
passes, and the judge reads the answer for that. `skipped-check-quiet` asks for the flag itself,
because the skill says to copy it as-is and never summarize it. What the block holds (the card,
the receipt's verdict) is not read: the skill does not say whether the card is pasted or pointed
at, and a workspace that is not a git repository has no receipt.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

RULE_LINE = re.compile(r"^:?-{1,}:?$")


def one_space(text: str) -> str:
    return " ".join(text.split()).casefold()


def heading_at(lines: list[str], name: str) -> int | None:
    """Index of the first line that is a heading named `name`, or None."""
    for index, line in enumerate(lines):
        opening = line.strip()
        if opening.startswith(("#", "**")) and opening.lstrip("#* \t").casefold().startswith(name.casefold()):
            return index
    return None


def block_span(lines: list[str]) -> tuple[int, int] | None:
    """(line that opens the first `<!--`, line that closes it), or None when none is closed."""
    for start, line in enumerate(lines):
        if "<!--" in line:
            for end in range(start, len(lines)):
                if "-->" in (lines[end] if end > start else line.split("<!--", 1)[1]):
                    return start, end
            return None
    return None


def cells(line: str) -> list[str] | None:
    """The cells of a table row, or None when the line is not one."""
    row = line.strip()
    if row.count("|") < 2:
        return None
    return [cell.strip() for cell in row.strip("|").split("|")]


def table(section: list[str]) -> tuple[int, int, list[list[str]]] | None:
    """(Before column, After column, data rows) of the first table with those two columns."""
    for index, line in enumerate(section):
        header = cells(line)
        if header is None:
            continue
        names = [cell.strip("*_` ").casefold() for cell in header]
        before = next((i for i, name in enumerate(names) if name.startswith("before")), None)
        after = next((i for i, name in enumerate(names) if name.startswith("after")), None)
        if before is None or after is None:
            continue
        rows = []
        for later in section[index + 1:]:
            row = cells(later)
            if row is None:
                break
            if all(RULE_LINE.match(cell) for cell in row if cell) or len(row) <= max(before, after):
                continue
            rows.append(row)
        return before, after, rows
    return None


def broken_rules(text: str, key: dict) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    lines = text.splitlines()
    quoted = ", ".join(f'"{name}"' for name in key["sections"])
    at = {name: heading_at(lines, name) for name in key["sections"]}
    missing = [name for name in key["sections"] if at[name] is None]
    if missing:
        broken.append(("section-missing", "the message has no section " + ", ".join(f'"{name}"' for name in missing)))
    in_order = not missing and [at[name] for name in key["sections"]] == sorted(at.values())
    if not missing and not in_order:
        broken.append(("section-order", f"the sections are not in the order {quoted}"))

    table_name, untested_name = key["table_section"], key["untested_section"]
    block = block_span(lines)
    if in_order and not (block and at[table_name] < block[0] and block[1] < at[untested_name]):
        broken.append(("card-block-missing", f'no closed <!-- --> block between "{table_name}" and "{untested_name}"'))

    def section(name: str) -> list[str]:
        ends = [index for index in (*at.values(), block[0] if block else None) if index is not None and index > at[name]]
        return lines[at[name]:min(ends, default=len(lines))]

    if at[table_name] is not None:
        found = table(section(table_name))
        if found is None:
            broken.append(("table-missing", f'"{table_name}" has no table with a Before and an After column'))
        else:
            before, after, rows = found
            for wanted in key["rows"]:
                carrying = [row for row in rows if one_space(wanted["after"]) in one_space(row[after])]
                if wanted["before"] is None:
                    if not carrying:
                        broken.append(("value-not-quoted", f'no row of the table carries "{wanted["after"]}" under After; '
                                                           "a value is quoted as the command produced it"))
                    elif not any(one_space(key["unmeasured_says"]) in one_space(row[before]) for row in carrying):
                        broken.append(("unmeasured-side-filled",
                                       f'the row with "{wanted["after"]}" under After says "{carrying[0][before]}" under Before; '
                                       f'that side was not measured and says "{key["unmeasured_says"]}"'))
                elif not any(one_space(wanted["before"]) in one_space(row[before]) for row in carrying):
                    broken.append(("value-not-quoted", f'no row of the table carries "{wanted["before"]}" under Before and '
                                                       f'"{wanted["after"]}" under After; a value is quoted as the command produced it'))

    if at[untested_name] is not None:
        said = one_space("\n".join(section(untested_name)))
        for flag in key["skipped_checks"]:
            if flag.casefold() not in said:
                broken.append(("skipped-check-quiet", f'"{untested_name}" does not carry {flag}; a skipped check is never kept quiet'))
        if not any(mark.casefold() in said for mark in key["gap_marks"]):
            broken.append(("gap-quiet", f'"{untested_name}" does not name the side that was not measured '
                                        f'(any of: {", ".join(key["gap_marks"])})'))
    return broken


def main(workspace: str, testdata: str) -> int:
    key = json.loads((pathlib.Path(testdata) / "answer-key.json").read_text(encoding="utf-8"))
    saved = pathlib.Path(workspace) / key["saved_file"]
    try:
        text = saved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = "is missing from the files the run left" if not saved.exists() else f"cannot be read: {exc}"
        print(f"output-missing: {key['saved_file']} {reason}", file=sys.stderr)
        return 1
    broken = broken_rules(text, key)
    for rule, what in broken:
        print(f"{rule}: {what}", file=sys.stderr)
    rules = list(dict.fromkeys(rule for rule, _what in broken))
    if len(rules) > 1:
        print(f"{len(rules)} rules broken: {', '.join(rules)}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
