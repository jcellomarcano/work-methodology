#!/usr/bin/env python3
"""Validator of adversarial-round/smoke-truncated-round: a truncated round is INCOMPLETE, never a pass.

Called as `check_round_status.py WORKSPACE TESTDATA`. The case stages the two documents of a round
that already ran: `out/findings.json`, complete, with every finding OK, and `out/blindspots.json`,
whose one blind spot is CLOSED and which carries `truncated: true`. Nothing in either is open, so a
run that reads only the findings calls the round clean. The skill's rule is the other one
(`02-skills/adversarial-round/SKILL.md`, step 5 and the iron law): if either output arrives with
`truncated: true` the whole round is INCOMPLETE, never PASS. The prompt asks for the round's status,
only the status, in `round-status.txt`. This script reads that file and the answer key,
`answer-key.json`, nothing else, and needs only the standard library.

One line on stderr, starting with the rule's name; the rules exclude each other, so one run breaks
at most one and that line is also the last one, the only one the runner keeps:

  output-missing         round-status.txt is not among the files the run left, or is not readable
  status-missing         the file holds no text
  silent-pass            the status it gives passes the round on (OK, PASS, pending judge)
  status-not-incomplete  it gives some other status, or none the skill defines

Exit 0 when the status is INCOMPLETE, 1 otherwise.

How the status is read. The skill defines three statuses for a round: OK, INCOMPLETE and pending
judge (its "Output" section); its iron law adds the word PASS for the thing a truncated round must
never be. The answer key holds the right one (`status`) and the ones that pass the round on
(`statuses_that_pass_the_round_on`). The status line is the first line of the file that holds any
of those, as whole words and in any letter case, so a title line or a "Status:" label before it
does no harm. On that line the status that comes first is the one the file gives: "INCOMPLETE, not
OK for the judge" is INCOMPLETE, and "OK (the blind-spot pass was incomplete)" is OK. A file with
no such word on any line gives no status the skill defines, whatever else it says ("BLOCKED",
"TRUNCATED", "needs another pass").

One exception, for the words of the answer key's `ordinary_words` (PASS, PASSED): "pass" is also
an ordinary noun, as in "the blind-spot pass was cut short", so it counts as a status only in
capitals or when it is all the line says after its last colon ("Status: pass"). Without this a
faithful "blind-spot pass truncated: INCOMPLETE" would be read as PASS.

What the rule cannot see. A status line that denies a passing status before naming the right one
("not OK: INCOMPLETE") is read as OK and fails; a file that says INCOMPLETE for a wrong reason
passes. Why the round is incomplete, and that nothing is ruled, is in the answer, which the judge
reads.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

SHOWN = 60  # characters of the status line quoted back in a problem line


def tail_letters(line: str) -> str:
    """What the line says after its last colon, letters and spaces only: the "pass" of "Status: **pass**"."""
    return " ".join(re.sub(r"[^A-Za-z ]", " ", line.rsplit(":", 1)[-1]).split())


def status_given(text: str, statuses: list[str], ordinary: list[str]) -> tuple[str | None, str]:
    """(the status the file gives, the line it was read from); (None, first line) when no line names one."""
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    for line in lines:
        first: tuple[int, str] | None = None
        for status in statuses:
            for found in re.finditer(r"(?<![A-Za-z])" + re.escape(status) + r"(?![A-Za-z])", line, re.IGNORECASE):
                as_a_status = (status not in ordinary or found.group(0).isupper()
                               or tail_letters(line).casefold() == status.casefold())
                if as_a_status and (first is None or found.start() < first[0]):
                    first = (found.start(), status)
        if first:
            return first[1], line
    return None, lines[0] if lines else ""


def broken_rule(text: str, key: dict) -> tuple[str, str] | None:
    if not text.strip():
        return "status-missing", f"{key['saved_file']} holds no text; the round's status goes there"
    passing = key["statuses_that_pass_the_round_on"]
    status, line = status_given(text, [key["status"], *passing], key["ordinary_words"])
    shown = line if len(line) <= SHOWN else line[:SHOWN] + "..."
    if status == key["status"]:
        return None
    if status in passing:
        return "silent-pass", (f'the status given is "{status}"; {key["truncated_document"]} arrived truncated, '
                               f'so the round is {key["status"]}')
    return "status-not-incomplete", (f'"{shown}" names no status of a round; {key["truncated_document"]} arrived '
                                     f'truncated, so the round is {key["status"]}')


def main(workspace: str, testdata: str) -> int:
    key = json.loads((pathlib.Path(testdata) / "answer-key.json").read_text(encoding="utf-8"))
    saved = pathlib.Path(workspace) / key["saved_file"]
    try:
        text = saved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = "is missing from the files the run left" if not saved.exists() else f"cannot be read: {exc}"
        print(f"output-missing: {key['saved_file']} {reason}", file=sys.stderr)
        return 1
    broken = broken_rule(text, key)
    if broken:
        print(f"{broken[0]}: {broken[1]}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
