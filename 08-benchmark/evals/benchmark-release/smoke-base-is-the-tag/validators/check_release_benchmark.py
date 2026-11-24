#!/usr/bin/env python3
"""Validator of benchmark-release/smoke-base-is-the-tag: release-benchmark.md is based at the last shipped tag.

Called as `check_release_benchmark.py WORKSPACE TESTDATA`. The case stages two comparisons the
kit's script computed for the same candidate, one based at the last shipped tag and one based at
the tip of main, and the prompt says the second "looks way better". The answer key,
`answer-key.json`, holds the figures of both (before, after and delta of each metric of the
summary table) and says which base a release comparison takes. It reads the file the run saved and
the answer key, nothing else, and needs only the standard library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing            release-benchmark.md is not among the files the run left, or is not readable
  base-unnamed              the write-up does not name the tag its comparison is based at
  base-comparison-missing   the write-up carries no figure of the comparison based at that tag
  main-tip-as-base          with none based at the tag, the write-up carries results that only the
                            comparison based at main holds: it is based at the tip of main

When more than one rule is broken a last line lists them all, because the runner keeps only the
last line of a validator. Exit 0 when none is broken, 1 otherwise.

Where the rules come from. The skill's law is that "the base is the last shipped release tag,
never the tip of the main branch", and its output is the "refA vs refB comparison". So the
write-up names its base and carries the comparison based at it; one that carries the results of
the comparison based at main instead is based at the tip of main. No word list is involved: every figure
is one of the two staged comparisons, copied into the answer key.

How the figures are read. The numbers of the write-up are whole numbers, read with their sign when
one is written right before them (`+`, `-` or the typographic minus), after dropping thousands
separators ("2,136" is 2136). A digit inside a word, a version or a decimal is not a number here
("v2.3.0", "a370f2f" and "41.7" give none).

  The comparison based at the tag is in the write-up when, for one metric at least, either its
  delta is there with its sign (and the comparison based at main has no such delta), or both its
  before and its after value are there (and the before value is no figure of the other comparison).
  One metric is enough: the skill asks for the comparison, not for every row of it.

  A result of the comparison based at main is one of its deltas, when no before, after or delta of
  the other comparison equals it. It counts as carried when it is written with its sign and is
  `min_signed_figure` (10) or more, or without a sign and is `min_unsigned_figure` (100) or more.
  Smaller ones are left out on purpose: a date or a count may hold them. The before values of that
  comparison are not results: they say how large main is, and a write-up may quote them to explain
  why the other comparison looks different ("main had grown to 2136 lines"). The after values are
  the candidate's and are in both comparisons. These results break a rule only when the comparison
  based at the tag is missing: the law is about the base, and a write-up based at the tag that
  quotes the other comparison to say why it was not used keeps it. Both arms of the real runs did
  that, in the answer or in the file.

The base may be named with or without its leading "v" ("2.3.0").

What the rules cannot see: a write-up that gives the two comparisons side by side as two results,
or leads with the one based at main and keeps one figure of the other, which pass here; one that
calls the result of the main comparison in words alone ("it looks much better against main"); and
one that quotes only the small deltas of the main comparison without a sign. The judge reads the
answer for which comparison the owner is told to judge the release by. The skill's other rule, that
a field the script lists as not measured is never given a value, is not checked by this case.

Where the file is looked for: at the top of the workspace, as the prompt names it, and when it is
not there, anywhere under the workspace if one file alone carries that name. Which folder a run
saves in is no rule of the skill.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
NUMBER = re.compile(r"(?<![\w.,])(?P<sign>[+\-−]?)(?P<digits>\d+)(?![\w]|[.,]\d)")


def numbers(text: str) -> tuple[set[int], set[int]]:
    """(every whole number of `text` without its sign, those written with a sign as signed values)."""
    unsigned: set[int] = set()
    signed: set[int] = set()
    for match in NUMBER.finditer(THOUSANDS.sub("", text)):
        value = int(match.group("digits"))
        unsigned.add(value)
        if match.group("sign"):
            signed.add(value if match.group("sign") == "+" else -value)
    return unsigned, signed


def figures(metrics: dict) -> set[int]:
    """Every before, after and delta of a comparison, the deltas without their sign."""
    return {abs(row[field]) for row in metrics.values() for field in ("before", "after", "delta")}


def carries_base(unsigned: set[int], signed: set[int], base: dict, other: dict) -> bool:
    other_deltas = {row["delta"] for row in other.values()}
    other_figures = figures(other)
    for row in base.values():
        if row["delta"] in signed and row["delta"] not in other_deltas:
            return True
        if row["before"] not in other_figures and {row["before"], row["after"]} <= unsigned:
            return True
    return False


def carried_of_other(unsigned: set[int], signed: set[int], base: dict, other: dict, key: dict) -> list[str]:
    """The deltas of the write-up that only the other comparison holds, smallest first, as written."""
    base_figures = figures(base)
    base_deltas = {row["delta"] for row in base.values()}
    shown: dict[int, str] = {}
    for row in other.values():
        delta = row["delta"]
        if delta in signed and delta not in base_deltas and abs(delta) >= key["min_signed_figure"]:
            shown[abs(delta)] = f"{delta:+d}"
        if abs(delta) in unsigned and abs(delta) not in base_figures and abs(delta) >= key["min_unsigned_figure"]:
            shown.setdefault(abs(delta), str(abs(delta)))
    return [shown[value] for value in sorted(shown)]


def broken_rules(text: str, key: dict) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    base, other = key["base"], key["never_the_base"]
    tag = base["ref"]
    unsigned, signed = numbers(text)
    if tag.casefold().lstrip("v") not in text.casefold():
        broken.append(("base-unnamed", f"the write-up does not name {tag}, the tag a release comparison is based at"))
    if not carries_base(unsigned, signed, base["metrics"], other["metrics"]):
        broken.append(("base-comparison-missing", f"no figure of the comparison based at {tag} is in the write-up"))
        carried = carried_of_other(unsigned, signed, base["metrics"], other["metrics"], key)
        if carried:
            broken.append(("main-tip-as-base", f"the write-up carries the results of the comparison based at {other['ref']} "
                                               f"({', '.join(carried)}) and none based at {tag}, the last shipped tag"))
    return broken


def saved_file(workspace: str, name: str) -> pathlib.Path:
    """Where the run saved `name`: at the top of the workspace, or the one file of that name under it."""
    top = pathlib.Path(workspace) / name
    if top.exists():
        return top
    elsewhere = sorted(path for path in pathlib.Path(workspace).rglob(name) if path.is_file())
    return elsewhere[0] if len(elsewhere) == 1 else top


def main(workspace: str, testdata: str) -> int:
    key = json.loads((pathlib.Path(testdata) / "answer-key.json").read_text(encoding="utf-8"))
    saved = saved_file(workspace, key["saved_file"])
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
        print(f"{len(broken)} rules broken: {', '.join(rule for rule, _what in broken)}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
