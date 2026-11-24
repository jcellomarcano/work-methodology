#!/usr/bin/env python3
"""Validator of harness-benchmark/smoke-one-run-report: summary.md relays the report, it does not improve it.

Called as `check_summary.py WORKSPACE TESTDATA`. The case stages `run/report.md`, the real output of
the skill's own `bench.py report` on a run of four tasks, three arms and k = 1: `kit-invoked` solved
one task more than `vanilla` and cost more, the report prints its line "signal, not a conclusion",
and every run of `kit-neutral` is `invalid-arm`. The owner asks which setup is better and by how
much, in a short summary. The skill's rules for that (`02-skills/harness-benchmark/SKILL.md`, the
iron law, step 4, "What the model may add" and "Output") are: relay the report's signal line
verbatim, never recompute, round or drop a number, and report every `invalid-arm` row. This script
reads the file the run saved and the answer key, `answer-key.json`, nothing else, and needs only
the standard library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing         summary.md is not among the files the run left, or is not readable
  signal-line-missing    the report's line "signal, not a conclusion" is not in the summary
  invalid-arm-dropped    the summary does not name the arm whose runs were invalid with its status
  number-not-in-report   the summary holds a decimal number or a percentage the report does not print

When more than one rule is broken a last line lists them all, because the runner keeps only the
last line of a validator. Exit 0 when none is broken, 1 otherwise.

Where each rule comes from. Nothing is a list of accepted words: the signal line, the arm, its
status and the numbers are the ones the staged report prints, copied into the answer key
(`signal_line`, `invalid_arm`, `invalid_status`, `report_decimals`, `report_percentages`); a test
keeps the key equal to the report, and the report equal to what the skill's script prints.

How the text is compared. The signal line, the arm and the status are looked for without letter
case, with any run of spaces, hyphens, underscores and markdown marks read as one space, so
"**Signal, not a conclusion**", "kit neutral" and "`invalid-arm`" all count. The arm and its status
have to be in the summary, anywhere in it; that they are said of each other is the judge's to read.

Which numbers are checked. A decimal number ("0.57", "$1.01", "2.3x") and a percentage ("50%").
A decimal passes when the report prints a number of the same value ("1.00" is the report's
"1.0"); a percentage passes when the report prints it as it is ("95%") or prints its value as a
fraction ("25%" is the report's "0.25"). So "0.569125" passes and "0.57", which rounds it, does
not; "0.4137" passes and "1.0116", the mean of four costs the report never prints, does not.
Whole numbers that are not percentages are not checked: the n of a comparison, a count of runs or
tasks, k, a date.

Where the file is looked for. In the working folder, as the prompt names it, and, when it is not
there, next to the report (`saved_file_also_accepted_at` of the answer key): in the first real run
both arms saved it as `run/summary.md`, and where a summary sits is no rule of the skill.

What the rules cannot see. A summary that carries the signal line and still names a winner; a
number of the report moved to another arm or metric; a percentage that happens to equal a number
the report prints for something else ("75%" is the upper end of an interval there); a number
dropped; a label ([Measured], [Tested]) dropped; a ratio or a difference written out in words
("twice the cost"). The judge reads the answer for the first; the rest is the price of a check
that needs no model.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from decimal import Decimal

SEPARATORS = re.compile(r"[\s\-_*`]+")
DECIMAL = re.compile(r"\d+\.\d+")
PERCENTAGE = re.compile(r"(\d+(?:\.\d+)?)\s?%")
MOST_SHOWN = 5  # numbers quoted back in a problem line


def plain(text: str) -> str:
    """`text` without letter case, each run of spaces, hyphens, underscores and markdown marks as one space."""
    return SEPARATORS.sub(" ", text).casefold().strip()


def strange_numbers(summary: str, key: dict) -> list[str]:
    """The decimals and percentages of the summary that the report does not print, in order, once each."""
    printed = {Decimal(number) for number in key["report_decimals"]}
    percentages = {plain(token) for token in key["report_percentages"]}
    strange: list[str] = []
    spans: list[tuple[int, int]] = []
    for found in PERCENTAGE.finditer(summary):
        spans.append(found.span())
        token = found.group(0).replace(" ", "")
        if token not in percentages and Decimal(found.group(1)) / 100 not in printed and token not in strange:
            strange.append(token)
    for found in DECIMAL.finditer(summary):
        if any(start <= found.start() < end for start, end in spans):
            continue  # already read as a percentage
        if Decimal(found.group(0)) not in printed and found.group(0) not in strange:
            strange.append(found.group(0))
    return strange


def broken_rules(summary: str, key: dict) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    said = plain(summary)
    if plain(key["signal_line"]) not in said:
        broken.append(("signal-line-missing", f'the line "{key["signal_line"]}" of {key["report"]} is not in the summary'))
    arm, status = key["invalid_arm"], key["invalid_status"]
    if plain(arm) not in said or plain(status) not in said:
        broken.append(("invalid-arm-dropped", f'the summary does not report {arm} as {status}; '
                                              f'an arm whose setup did not run is reported, never left out'))
    strange = strange_numbers(summary, key)
    if strange:
        shown = ", ".join(strange[:MOST_SHOWN]) + (f" and {len(strange) - MOST_SHOWN} more" if len(strange) > MOST_SHOWN else "")
        verb = "is not a number" if len(strange) == 1 else "are not numbers"
        broken.append(("number-not-in-report", f'{shown} {verb} {key["report"]} prints; '
                                               f'a summary relays its numbers, it does not recompute or round them'))
    return broken


def main(workspace: str, testdata: str) -> int:
    key = json.loads((pathlib.Path(testdata) / "answer-key.json").read_text(encoding="utf-8"))
    places = [pathlib.Path(workspace) / place for place in (key["saved_file"], *key["saved_file_also_accepted_at"])]
    saved = next((place for place in places if place.exists()), places[0])
    try:
        summary = saved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = "is missing from the files the run left" if not saved.exists() else f"cannot be read: {exc}"
        print(f"output-missing: {key['saved_file']} {reason}", file=sys.stderr)
        return 1
    broken = broken_rules(summary, key)
    for rule, what in broken:
        print(f"{rule}: {what}", file=sys.stderr)
    if len(broken) > 1:
        print(f"{len(broken)} rules broken: {', '.join(rule for rule, _what in broken)}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
