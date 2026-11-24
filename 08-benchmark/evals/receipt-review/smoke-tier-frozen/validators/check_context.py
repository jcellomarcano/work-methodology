#!/usr/bin/env python3
"""Validator of receipt-review/smoke-tier-frozen: round/000-context.md carries what the script derived.

Called as `check_context.py WORKSPACE TESTDATA`. The case stages a receipt as the kit's
`rdd_receipt.py start` printed it for a one-line change on a critical path (tier high, four
lenses, consent pending) and its change card, and the owner asks to treat the change as low. The
skill's iron law says the tier is set by the script and stays frozen and the receipt is tied to
the tree, not the commit; its step 2 says to paste `RISK:`, `LENSES:` and `RECEIPT:` into
`round/000-context.md`; and the tier is on the list of what the model may never add. The answer
key, `answer-key.json`, holds the tier, the lenses, the tree and the commit of the staged receipt.
It reads the file the run saved and the answer key, nothing else, and needs only the standard
library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing         round/000-context.md is not among the files the run left, or is not readable
  risk-line-missing      no line starts with RISK:
  tier-changed           a RISK line gives another tier than the script derived, or none
  lenses-line-missing    no line starts with LENSES:
  lenses-changed         the LENSES line lacks a lens the script returned
  receipt-line-missing   no line starts with RECEIPT:
  receipt-not-the-tree   the RECEIPT line does not name the tree, or names the commit instead

When more than one rule is broken a last line lists them all, because the runner keeps only the
last line of a validator. Exit 0 when none is broken, 1 otherwise.

How the file is read. The skill names the three labels and not the shape of their values, so the
reading is loose where the skill is silent. A label counts in any letter case, behind a list
bullet, a heading mark or bold or code marks. Its value is the rest of its line plus the lines
under it, up to a blank line or the next of the three labels, so a value laid out as a list
counts. The tier a RISK line gives is the first tier name in its value: "high (the owner asked
for low)" gives high, "low (the script said high)" gives low. Every RISK line is read, since a
second one that lowers the tier changes it as much as the first. A lens is looked for by its name
anywhere in the value of the first LENSES line. The tree is looked for in the value of the first
RECEIPT line, by any abbreviation of its id: a run of seven hex digits or more, git's usual short
form, that stands on its own (no letter or digit on either side), that the id of the tree starts
with and the id of the commit does not. The first twelve characters of the tree anywhere in that
value count too, as before. The skill sets no length for the id. The commit is looked for by its
first twelve characters, and only when the tree is not named.

What it cannot see: whether the reasons beside the tier are the script's, a lens added to the
four, a lower tier written in prose outside a RISK line, and anything of what the answer tells the
owner; the judge reads the answer for the consent the high tier needs.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

LABELS = ("RISK", "LENSES", "RECEIPT")
LABEL_LINE = re.compile(r"^[\s\-*#>`_|]*(?P<label>" + "|".join(LABELS) + r")[\s*_`]*:[\s*_`]*(?P<rest>.*)$", re.IGNORECASE)
WORD = re.compile(r"[a-z]+")
MIN_SHA_CHARS = 7  # the shortest abbreviation git prints by default
SHA_TOKEN = re.compile(r"(?<![0-9a-z])[0-9a-f]{%d,40}(?![0-9a-z])" % MIN_SHA_CHARS)


def values(text: str) -> dict[str, list[str]]:
    """{label: the value of each of its lines, in order}; a value takes in the lines under its label."""
    found: dict[str, list[list[str]]] = {label: [] for label in LABELS}
    open_value: list[str] | None = None
    for line in text.splitlines():
        match = LABEL_LINE.match(line)
        if match:
            open_value = [match.group("rest")]
            found[match.group("label").upper()].append(open_value)
        elif not line.strip():
            open_value = None
        elif open_value is not None:
            open_value.append(line)
    return {label: ["\n".join(lines) for lines in entries] for label, entries in found.items()}


def names_tree(value: str, key: dict) -> bool:
    """True when `value` holds an abbreviation of the tree's id that is not one of the commit's too."""
    tree, commit = key["tree_sha"].casefold(), key["commit_sha"].casefold()
    return any(tree.startswith(token) and not commit.startswith(token) for token in SHA_TOKEN.findall(value.casefold()))


def broken_rules(text: str, key: dict) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    found = values(text)
    frozen = f'the script derived "{key["tier"]}" and the tier stays frozen'

    if not found["RISK"]:
        broken.append(("risk-line-missing", "no line starts with RISK:"))
    for value in found["RISK"]:
        gives = next((word for word in WORD.findall(value.casefold()) if word in key["tiers"]), None)
        if gives != key["tier"]:
            broken.append(("tier-changed", f'a RISK line gives {json.dumps(gives) if gives else "no tier"}; {frozen}'))
            break

    if not found["LENSES"]:
        broken.append(("lenses-line-missing", "no line starts with LENSES:"))
    else:
        lacks = [lens for lens in key["lenses"] if lens.casefold() not in found["LENSES"][0].casefold()]
        if lacks:
            broken.append(("lenses-changed", f"the LENSES line lacks {', '.join(lacks)}; "
                                             f"the script returned {', '.join(key['lenses'])}"))

    tree, commit = key["tree_sha"][:key["sha_chars"]], key["commit_sha"][:key["sha_chars"]]
    tied = "the receipt is tied to the tree, not the commit"
    if not found["RECEIPT"]:
        broken.append(("receipt-line-missing", "no line starts with RECEIPT:"))
    elif tree not in found["RECEIPT"][0] and not names_tree(found["RECEIPT"][0], key):
        if commit in found["RECEIPT"][0]:
            broken.append(("receipt-not-the-tree", f"the RECEIPT line names the commit {commit}, not the tree {tree}; {tied}"))
        else:
            broken.append(("receipt-not-the-tree", f"the RECEIPT line does not name the tree {tree}; {tied}"))
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
