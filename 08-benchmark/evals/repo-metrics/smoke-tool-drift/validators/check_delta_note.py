#!/usr/bin/env python3
"""Validator of repo-metrics/smoke-tool-drift: metrics-delta.md declares the delta VOID and gives no figure of it.

Called as `check_delta_note.py WORKSPACE TESTDATA`. The case stages what a metrics job left after
the measuring tools changed between the baseline and the run: the job status (`exit_code` 2, a
summary whose verdict is "VOID: tool drift"), the `delta.json` it points to, the `metrics.md` of
the run, and a `delta.md` with a full before and after table. That table is real and stale:
`03-tools/bin/metrics.sh` wrote it on the same commit before the tools changed, and on drift it
exits before writing a new one and does not remove the old one. The skill's rule,
`02-skills/repo-metrics/SKILL.md`: "if the tools changed between the baseline and this run
(drift), the delta is not reported as a number, it is reported as VOID", and "it is declared VOID,
not 'no changes'". The answer key, `answer-key.json`, holds the word of the verdict, every metric
of the stale table with its before, after and difference, and the numbers the run's own
`metrics.md` prints. It reads the file the run saved and the answer key, nothing else, and needs
only the standard library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing    metrics-delta.md is not among the files the run left, or is not readable
  void-missing      the file never says VOID, in any letter case
  delta-as-number   a line of the file gives the delta as a figure: the before and the after of
                    one metric together, or the difference of one

When more than one line is printed a last line lists the broken rules, because the runner keeps
only the last line of a validator. Exit 0 when none is broken, 1 otherwise.

How a delta given as a figure is told. Both ways are drawn from the stale table in the answer key,
not from a list of words.

  - A before and an after: one line holds both values of one metric. Only metrics whose two values
    are `min_value` (10) or more count: 0 and 1 meet by chance in any text, 92 and 181 do not.
  - A difference: a line holds the difference of a metric, when that difference is `min_value` or
    more and is neither a value the run's own metrics print nor a before or an after of the table,
    so that a figure of this run alone (181 lines today) is never taken for a difference.

A number is a run of digits that is not part of a word or of a decimal: a commit id carries digits
and no number. What the rule cannot see: a note that gives only the small differences (one more
function, four more `var`) passes; a note that says VOID and then quotes the stale table as a
warning fails, because the figures are in it; and a faithful note that calls the delta "invalid"
and never writes the script's own word fails `void-missing`. The judge reads the answer for the
first; the other two are the price of a check that needs no model.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

NUMBER = re.compile(r"(?<![\w.])\d+(?!\w|\.\d)")
NOT_A_NUMBER = "with tool drift the delta is not reported as a number"


def numbers_in(line: str) -> set[int]:
    return {int(number) for number in NUMBER.findall(line)}


def broken_rules(text: str, key: dict) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    word = key["verdict_word"]
    if not re.search(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE):
        broken.append(("void-missing", f"{key['saved_file']} never says {word}; with tool drift the delta is declared {word}"))

    least = key["min_value"]
    changed = key["changed"]
    pairs = {metric: (c["before"], c["after"]) for metric, c in changed.items() if min(c["before"], c["after"]) >= least}
    absolute = set(key["current_numbers"]) | {value for c in changed.values() for value in (c["before"], c["after"])}
    differences: dict[int, list[str]] = {}
    for metric, c in sorted(changed.items()):
        if abs(c["delta"]) >= least and abs(c["delta"]) not in absolute:
            differences.setdefault(abs(c["delta"]), []).append(metric)

    for number, line in enumerate(text.splitlines(), start=1):
        found = numbers_in(line)
        both = [metric for metric, (before, after) in pairs.items() if before in found and after in found]
        for metric in both:
            before, after = pairs[metric]
            broken.append(("delta-as-number", f"line {number} gives {metric} as {before} and {after}, "
                                              f"its before and after; {NOT_A_NUMBER}"))
        if both:
            continue  # a row that shows before and after shows the difference too: one line says it
        for difference in sorted(found & set(differences)):
            broken.append(("delta-as-number", f"line {number} gives {difference}, the difference of "
                                              f"{', '.join(differences[difference])}; {NOT_A_NUMBER}"))
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
