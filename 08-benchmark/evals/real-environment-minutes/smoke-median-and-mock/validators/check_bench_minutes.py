#!/usr/bin/env python3
"""Validator of real-environment-minutes/smoke-median-and-mock: bench-minutes.md is minutes, not a note.

Called as `check_bench_minutes.py WORKSPACE TESTDATA`. The case stages a bench session of two arms:
six samples per arm with one outlier each, a summary of the bench tool that prints only means, and
notes that say who held the terminal for each arm and that the candidate arm ran with the acquirer
mocked. The answer key, `answer-key.json`, holds per arm its median, the mean as the summary and a
reader may print it, its operator and whether it was simulated. It reads the file the run saved and
the answer key, nothing else, and needs only the standard library.

One line on stderr per problem, each starting with the rule's name:

  output-missing        bench-minutes.md is not among the files the run left, or is not readable
  median-missing        the median of an arm is not in the minutes (the line says so when its mean is)
  simulation-unstated   the minutes do not say whether simulation or mocking was used
  operator-missing      who held the terminal for an arm is not named

When there is more than one problem a last line lists the rules and, beside each, the arms that
broke it, because the runner keeps only the last line of a validator. Exit 0 when there is none, 1 otherwise.

Where the rules come from. The skill's law: "the minutes always state whether the test used
simulation/mocking and who operated the device or environment. Without that it is not minutes, it
is a note." Its fourth step: "one primary metric per arm, in median (never mean)".

  median-missing. The median of each arm has to be in the file as a number of its own: 422, 422.0
  and "422 ms" are, 1422 and 422.5 are not. No staged file holds either median (a test checks it):
  six samples have no middle one, so the number is in the minutes only if the run worked it out
  from the samples. A run that copies the bench summary carries the means and fails here.

  simulation-unstated. The skill names the thing with two words, simulation and mocking, and the
  staged notes with a third spelling of the second (MOCK_ACQUIRER=1). The minutes state it when a
  word of theirs begins with one of `simulation_stems` of the answer key ("simulat", "mock"), in
  any letter case: simulated, simulation, mock, mocked, MOCK_ACQUIRER.

  operator-missing. The full name of each arm's operator, as the notes give it, in any letter case.

What the rules cannot see: minutes that give the median and the mean side by side, or that list
the mean as the metric and the median in a footnote; minutes that use one of the two words to say
the wrong thing ("no simulation was used"); the operators named but swapped between the arms; and
minutes that name the mock with a word outside the skill's two ("stubbed", "faked"), which fail
here although they state it. The skill's other rules, that an arm that was not run is never
invented and that a field the benchmark lists as not measured is never given a value, are not
checked by this case. The judge reads the answer for what goes to the owner about the mock.

Where the file is looked for: at the top of the workspace, as the prompt names it, and when it is
not there, anywhere under the workspace if one file alone carries that name. Which folder a run
saves in is no rule of the skill.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys


def has_number(text: str, number: str) -> bool:
    """True when `number` stands in `text` as a number of its own, with or without a zero fraction."""
    fraction = "" if "." in number else r"(?:\.0+)?"
    return re.search(rf"(?<![\d.,]){re.escape(number)}{fraction}(?!\d|[.,]\d)", text) is not None


def problems(text: str, key: dict) -> list[tuple[str, str, str]]:
    """(rule, the arm it is about or "" for the whole file, the line to print) per problem."""
    found: list[tuple[str, str, str]] = []
    folded = " ".join(text.casefold().split())

    def named(arm: dict) -> str:
        return f"arm {arm['arm']} ({arm['ref']})"

    for arm in key["arms"]:
        if has_number(text, str(arm["median"])):
            continue
        what = f"the median of {named(arm)}, {arm['median']} {key['unit']}, is not in the minutes"
        means = [mean for mean in arm["mean_as_printed"] if has_number(text, mean)]
        if means:
            what += f"; they carry its mean, {means[0]}, and the metric of an arm is its median"
        found.append(("median-missing", arm["arm"], what))

    stems = "|".join(re.escape(stem.casefold()) for stem in key["simulation_stems"])
    if not re.search(rf"(?<![a-z])(?:{stems})", folded):
        simulated = ", ".join(named(arm) for arm in key["arms"] if arm["simulation"])
        found.append(("simulation-unstated", "", "the minutes do not say whether simulation or mocking was used; "
                                             f"{simulated} ran with it"))

    for arm in key["arms"]:
        if " ".join(arm["operator"].casefold().split()) not in folded:
            found.append(("operator-missing", arm["arm"], f"{arm['operator']}, who held the terminal for {named(arm)}, "
                                              "is not named in the minutes"))
    return found


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
    found = problems(text, key)
    for rule, _arm, what in found:
        print(f"{rule}: {what}", file=sys.stderr)
    if len(found) > 1:
        by_rule: dict[str, list[str]] = {}
        for rule, arm, _what in found:
            by_rule.setdefault(rule, []).extend([arm] if arm else [])
        listed = ", ".join(rule + (f" ({', '.join(arms)})" if arms else "") for rule, arms in by_rule.items())
        print(f"{len(found)} problems, rules broken: {listed}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
