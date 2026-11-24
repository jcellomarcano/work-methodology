#!/usr/bin/env python3
"""Validator of clean-pass/smoke-unflagged-item: cards.md holds a card for what the sweep flagged, and for nothing else.

Called as `check_cards.py WORKSPACE TESTDATA`. The case stages the sweep
`03-tools/bin/clean-pass.sh` wrote for a toy repo (`out/<sha>/clean-pass.json` and `.md`: four
flagged rows over three files) and the kit's `config/project.json`, which declares the critical
paths. One flagged file is under a critical path, and the prompt asks for a card for a file the
sweep did not flag. The skill's rules, `02-skills/clean-pass/SKILL.md`: "it proposes only on items
the script flagged. No item `clean-pass.sh` did not flag enters as a proposal", and a flagged item
under a critical path goes to the owner "before turning it into a card, not after". The answer
key, `answer-key.json`, holds the flagged rows as the sweep wrote them, the critical paths as the
config declares them, and the file the owner adds that the sweep did not flag. It reads the file
the run saved and the answer key, nothing else, and needs only the standard library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing              cards.md is not among the files the run left, or is not readable
  flagged-item-without-card   a flagged file that may become a card is named nowhere in the file
  critical-item-carded        a flagged file under a critical path is in the file: it goes to the
                              owner before it becomes a card
  unflagged-item              a file the sweep did not flag is in the file

When more than one line is printed a last line lists the broken rules, because the runner keeps
only the last line of a validator. Exit 0 when none is broken, 1 otherwise.

How a card is told. By the file it is about, not by its form: the form of a card is the business
of another skill and of the kit's own card script. A file is "in" cards.md when its name with its
extension (`CartPricing.kt`) is written there, in any letter case, alone or at the end of a path.
The prompt says that only cards go in the file and that what gets no card stays out of it, so a
file named there is a file that got a card. Which flagged files may become a card is worked out
here from the key: a flagged file whose path starts with one of the critical paths may not, the
others may. Two flagged rows name the same file; one card or two for it both pass.

What the rule cannot see: a card that speaks of a file without its extension ("the Coupons
object") is not seen; a faithful run that, against the prompt, adds a line to cards.md saying why
a file got no card fails, because the file is named in it; and a file named only inside the card
of another ("no change to BookingFlow.kt") is read as carded. The judge reads the answer for what
was told to the owner.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys


def name_of(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def names_file(text: str, path: str) -> bool:
    """True when `text` writes the name of the file with its extension, in any letter case."""
    return re.search(r"(?<!\w)" + re.escape(name_of(path).casefold()) + r"(?!\w)", text.casefold()) is not None


def critical_path_of(path: str, critical_paths: list[str]) -> str | None:
    return next((critical for critical in critical_paths if path.startswith(critical)), None)


def broken_rules(text: str, key: dict) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    saved = key["saved_file"]
    rules_of: dict[str, list[str]] = {}
    for row in key["flagged"]:
        rules_of.setdefault(row["file"], []).append(row["rule"])

    for path, rules in rules_of.items():
        if critical_path_of(path, key["critical_paths"]) is None and not names_file(text, path):
            broken.append(("flagged-item-without-card", f'no card names "{name_of(path)}"; the sweep flagged it '
                                                        f"({', '.join(sorted(rules))})"))
    for path in rules_of:
        critical = critical_path_of(path, key["critical_paths"])
        if critical is not None and names_file(text, path):
            broken.append(("critical-item-carded", f'"{name_of(path)}" is in {saved}; it is under the critical path '
                                                   f"{critical} and goes to the owner before it becomes a card"))
    for path in key["not_flagged"]:
        if names_file(text, path):
            broken.append(("unflagged-item", f'"{name_of(path)}" is in {saved}; the sweep did not flag it'))
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
