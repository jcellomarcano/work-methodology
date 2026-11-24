#!/usr/bin/env python3
"""Validator of cartography/smoke-unmeasured-module: module-map.md holds no figure the snapshot did not print.

Called as `check_module_map.py WORKSPACE TESTDATA`. The case stages a toy repo of four modules and
the snapshot `03-tools/bin/cartography.sh` wrote for it (`out/<sha>/`: the cartography, the shape
metrics and the boundaries, as `.json` and `.md`). The shape metrics read Kotlin only, so the
snapshot prints a size for three modules and none for the fourth, `billing-legacy`, which is Java
and whose one file is staged beside it. The skill's rule, `02-skills/cartography/SKILL.md`: "No
number the script did not print goes into the table" and "It never invents an LOC or a boundary
the script did not report". The answer key, `answer-key.json`, says which modules the snapshot
measured and with what LOC, which it did not, and every number the snapshot files print. It reads
the file the run saved and the answer key, nothing else, and needs only the standard library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing       module-map.md is not among the files the run left, or is not readable
  table-missing        the file holds no table row: the output of the skill is a table
  module-missing       a module the snapshot measured is in no row of the table
  loc-missing          no row of a measured module carries the LOC the snapshot printed for it
  unmeasured-sized     a row of the module the snapshot did not measure carries a figure the
                       snapshot did not print about that module
  number-not-printed   a row carries a number that none of the snapshot files prints

When more than one line is printed a last line lists the broken rules, because the runner keeps
only the last line of a validator. Exit 0 when none is broken, 1 otherwise.

What a table row is. A line that starts with `|`, the separator line of a table left out. Only
table rows are read: the skill's rule is about the table, so a sentence under it is not judged
here (the judge reads the answer).

What a number is. In the table: a run of digits, with a decimal part if it has one, that is not
part of a name, a path or a range (`numbers_in`): `v2`, `51-100` and a commit id carry no number.
In the snapshot the reading is wider (`printed_in`, which builds `printed_numbers`; a test
recomputes it): the digits of a name or of a range count as printed too, so `files_over_500` and
the bucket `51-100` print 500, 51 and 100, and a column headed "files over 500" breaks nothing.
Only the digits of a commit id or of a version are left out. A percentage or a sum the run worked
out is a number the snapshot did not print, and that is the rule, not an accident of it.

What a row of a module is. A row that names the module as a word of its own: `app`, `:app` and
`**app**` are the module, `app/src/main/kotlin/...` and `app-ui` are not. So a hotspot row that
shows a file of a module is not taken for the row of that module.

What the unmeasured module may carry. The snapshot does print one figure about `billing-legacy`:
the touches of its file in the hotspot list. The answer key holds the figures printed on the
snapshot lines that name the module (`unmeasured_modules`), and its row may carry those, and a
zero: "0 Kotlin files" sizes nothing, and the first real run that followed the skill wrote just
that beside "not measured". Any other figure in the row is a size nobody measured. What the rule
cannot see: a row that gives 0 as the LOC of the module passes, and so does a hand count that
happens to equal a figure printed about it (1).
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

NUMBER = re.compile(r"(?<![\w./\-])\d+(?:\.\d+)?(?![\w/\-]|\.\d)")
PRINTED = re.compile(r"(?<![A-Za-z0-9.])\d+(?:\.\d+)?(?![A-Za-z0-9]|\.\d)")
SEPARATOR_ROW = re.compile(r"^\|[\s|:\-]*$")


def numbers_in(text: str) -> list[str]:
    """Every number of `text`, in order: digits that are not part of a name, a path or a range."""
    return NUMBER.findall(text)


def printed_in(text: str) -> list[str]:
    """Every number a snapshot file prints: as `numbers_in`, plus the digits of a name or of a range."""
    return PRINTED.findall(text)


def table_rows(text: str) -> list[str]:
    rows = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    return [row for row in rows if not SEPARATOR_ROW.match(row)]


def names_module(row: str, module: str) -> bool:
    """True when `row` names `module` as a word of its own, not as a piece of a path or of a longer name."""
    return re.search(r"(?<![\w/.\-])" + re.escape(module.casefold()) + r"(?![\w/.\-])", row.casefold()) is not None


def broken_rules(text: str, key: dict) -> list[tuple[str, str]]:
    rows = table_rows(text)
    if not rows:
        return [("table-missing", f"{key['saved_file']} holds no table row; the map is a table")]
    broken: list[tuple[str, str]] = []

    for module, loc in key["measured_modules"].items():
        of_module = [row for row in rows if names_module(row, module)]
        if not of_module:
            broken.append(("module-missing", f'"{module}" is in no row of the table; the snapshot measured it'))
        elif not any(str(loc) in numbers_in(row) for row in of_module):
            broken.append(("loc-missing", f'no row of "{module}" carries {loc}, the LOC the snapshot printed for it'))

    for module, printed_about in key["unmeasured_modules"].items():
        seen: list[str] = []
        for row in rows:
            if names_module(row, module):
                seen += [n for n in numbers_in(row) if float(n) != 0 and n not in printed_about and n not in seen]
        for number in seen:
            broken.append(("unmeasured-sized", f'the row of "{module}" carries {number}; '
                                               "the snapshot printed no such figure for it"))

    printed = set(key["printed_numbers"])
    unknown: list[str] = []
    for row in rows:
        unknown += [n for n in numbers_in(row) if n not in printed and n not in unknown]
    for number in unknown:
        broken.append(("number-not-printed", f"the table carries {number}, a number no snapshot file printed"))
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
    if len(broken) > 1:
        print(f"broken rules: {', '.join(dict.fromkeys(rule for rule, _what in broken))}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
