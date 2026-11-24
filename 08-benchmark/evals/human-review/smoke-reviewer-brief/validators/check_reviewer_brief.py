#!/usr/bin/env python3
"""Validator of human-review/smoke-reviewer-brief: round/004-brief.md is the brief the skill dictates.

Called as `check_reviewer_brief.py WORKSPACE TESTDATA`. The run is asked for the brief of the style
reviewer of a staged reply, `round/003-reply.md`, and nothing more: no reviewer is launched. The
skill's first step says what that brief holds (02-skills/human-review/SKILL.md, step 1): the role
`generic-human-reviewer`; `INPUTS` = the reply and `07-communication/rules.md`; `CONSTRAINTS` =
rules COM-07, COM-12, COM-13, COM-16, COM-17 and the declared reader; `OUTPUT` = the round
directory; `BUDGET` = 15000 tokens, 10 calls. Its iron law says the reply is not rewritten at this
step: the reviewer returns findings and the author fixes them afterwards. The answer key,
`answer-key.json`, holds those values and the sha256 of the staged reply. The validator reads the
brief, the reply and the answer key, nothing else, and needs only the standard library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing         round/004-brief.md is not among the files the run left
  field-missing          one of INPUTS, CONSTRAINTS, OUTPUT, BUDGET is absent or empty
  role-missing           the brief does not name generic-human-reviewer anywhere
  inputs-missing         INPUTS does not name the reply or rules.md
  rules-missing          CONSTRAINTS lacks one of the five rules the reviewer judges
  rule-outside-the-five  CONSTRAINTS names another COM rule: never a rule outside the five
  reader-missing         CONSTRAINTS does not declare the reader the owner gave (public)
  output-not-round       OUTPUT does not name the round directory
  budget-wrong           BUDGET does not carry 15000 tokens and 10 calls
  reply-rewritten        round/003-reply.md changed or is gone

When more than one rule is broken a last line lists them all, because the runner keeps only the
last line of a validator. Exit 0 when none is broken, 1 otherwise.

How the brief is read. A field opens on a line that starts with one of the twelve names of the
kit's brief (`brief_fields` of the answer key: ROLE, OBJECTIVE ... EVIDENCE), in any letter case,
after any markdown dressing (a bullet, a heading mark, bold, backticks, a table bar, a number), and
followed by a colon, an equals sign, a table bar or the end of the line. Its value is the rest of
that line and every line up to the next field. So the kit's own layout (`INPUTS: ...` at column 0),
bold labels, one heading per field and a two-column table all read the same. Only the four fields
the skill's text fills are required: the package the run loads does not carry the template
(`04-templates/brief.md`), so the other eight names are not asked of it.

How the values are read. Rule ids are `COM-NN`, and `COM-12/13` counts as both. The reader is the
word of the answer key (`public`) anywhere in CONSTRAINTS. The round directory is its name
(`round`) anywhere in OUTPUT. In BUDGET, 15000 may be written 15000, 15,000, 15.000, 15 000, 15_000
or 15k, and 10 must stand as a number of its own (100 and 10000 are not 10).

What it cannot see. Whether the brief is a good one beyond those values, whether it has the twelve
fields in the template's order (the kit's own brief check measures that, on a machine that has the
template), and everything after the brief: the reviewer's run, its verdict, the findings going back
to the author, the second pass.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

DRESSING = r"[\s#>*+|`_\-]*(?:\d+[.)]\s*)?[*`_]*"
RULE_ID = re.compile(r"COM-(\d{2})((?:\s*/\s*\d{2})*)")
THOUSANDS = re.compile(r"(?<=\d)[,._ ](?=\d{3}(?!\d))")


def read_fields(brief: str, names: list[str]) -> dict[str, str]:
    """{field name: value} of the brief; the first occurrence of a field wins."""
    by_length = sorted(names, key=len, reverse=True)  # ALREADY READ before any shorter name
    header = re.compile(r"^" + DRESSING + r"(?P<name>" + "|".join(map(re.escape, by_length)) + r")[*`_]*\s*(?:[:=|]|$)(?P<rest>.*)$",
                        re.IGNORECASE)
    fields: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in brief.splitlines():
        match = header.match(line)
        if match:
            name = match.group("name").upper()
            current = fields.setdefault(name, []) if name not in fields else None
            if current is not None:
                current.append(match.group("rest"))
        elif current is not None:
            current.append(line)
    return {name: " ".join(" ".join(lines).replace("|", " ").split()).strip("*`_ ") for name, lines in fields.items()}


def rule_ids(text: str) -> list[str]:
    """Every COM rule id of `text`, in order, `COM-12/13` read as COM-12 and COM-13."""
    found: list[str] = []
    for match in RULE_ID.finditer(text):
        found.append(f"COM-{match.group(1)}")
        found += [f"COM-{number}" for number in re.findall(r"\d{2}", match.group(2))]
    return list(dict.fromkeys(found))


def carries_budget(text: str, tokens: int, calls: int) -> bool:
    """True when `text` holds both numbers of the skill's budget."""
    plain = THOUSANDS.sub("", text.casefold())
    thousands = tokens // 1000
    spent, found = re.subn(rf"(?<![\w.]){tokens}(?!\d)|(?<![\w.]){thousands}\s*k\b", " ", plain)
    return bool(found) and re.search(rf"(?<![\d.,]){calls}(?![\d]|[.,]\d)", spent) is not None


def broken_rules(brief: str, workspace: pathlib.Path, key: dict) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    fields = read_fields(brief, key["brief_fields"])
    for name in key["fields_the_skill_fills"]:
        if not fields.get(name):
            broken.append(("field-missing", f"the brief has no {name} field"))

    if key["role"] not in brief.casefold():
        broken.append(("role-missing", f"the brief does not name {key['role']}"))

    inputs = fields.get("INPUTS")
    if inputs:
        for path in key["inputs"]:
            if path not in inputs:
                broken.append(("inputs-missing", f"INPUTS does not name {path}"))

    constraints = fields.get("CONSTRAINTS")
    if constraints:
        named = rule_ids(constraints)
        for rule in key["rules"]:
            if rule not in named:
                broken.append(("rules-missing", f"CONSTRAINTS does not name {rule}"))
        for rule in named:
            if rule not in key["rules"]:
                broken.append(("rule-outside-the-five",
                               f"CONSTRAINTS names {rule}; the reviewer judges only {', '.join(key['rules'])}"))
        if key["reader"] not in constraints.casefold():
            broken.append(("reader-missing", f"CONSTRAINTS does not declare the reader ({key['reader']})"))

    output = fields.get("OUTPUT")
    if output and key["output_dir"] not in output.casefold():
        broken.append(("output-not-round", f"OUTPUT does not name the round directory ({key['output_dir']}/)"))

    budget = fields.get("BUDGET")
    if budget and not carries_budget(budget, key["budget"]["tokens"], key["budget"]["calls"]):
        broken.append(("budget-wrong",
                       f"BUDGET does not carry {key['budget']['tokens']} tokens and {key['budget']['calls']} calls"))

    reply = workspace / key["reply"]["path"]
    after = "its author fixes it after the findings, never the run that briefs the reviewer"
    if not reply.is_file():
        broken.append(("reply-rewritten", f"{key['reply']['path']} is gone; {after}"))
    elif hashlib.sha256(reply.read_bytes()).hexdigest() != key["reply"]["sha256"]:
        broken.append(("reply-rewritten", f"{key['reply']['path']} changed; {after}"))
    return broken


def main(workspace: str, testdata: str) -> int:
    key = json.loads((pathlib.Path(testdata) / "answer-key.json").read_text(encoding="utf-8"))
    saved = pathlib.Path(workspace) / key["saved_file"]
    try:
        brief = saved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = "is missing from the files the run left" if not saved.exists() else f"cannot be read: {exc}"
        print(f"output-missing: {key['saved_file']} {reason}", file=sys.stderr)
        return 1
    broken = broken_rules(brief, pathlib.Path(workspace), key)
    for rule, what in broken:
        print(f"{rule}: {what}", file=sys.stderr)
    if len(broken) > 1:
        print(f"{len(broken)} rules broken: {', '.join(rule for rule, _what in broken)}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
