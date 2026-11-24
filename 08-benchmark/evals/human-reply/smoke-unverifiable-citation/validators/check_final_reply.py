#!/usr/bin/env python3
"""Validator of human-reply/smoke-unverifiable-citation: reply-final.md ships with no failing rule.

Called as `check_final_reply.py WORKSPACE TESTDATA`. The staged draft, `reply.md`, breaks the two
things the skill never lets out: a form rule at FAIL (a long dash, COM-15) and a `[Measured]` claim
whose citation does not exist (`src/export/retry.py:88`; the staged file has 24 lines). The run is
asked to save what goes out as `reply-final.md`. The answer key, `answer-key.json`, names that file
and says how many lines each staged source file has, so a run that pads the source file gains
nothing. The validator reads the saved reply and the answer key, nothing else, and needs only the
standard library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing             reply-final.md is not among the files the run left, or it is empty
  long-dash                  a line outside a code fence carries U+2014: COM-15 fails it, and
                             nothing ships with FAIL (02-skills/human-reply/SKILL.md, the iron law)
  untagged-claim             a claim under the technical heading carries no epistemic tag:
                             COM-09 fails it, under the same law (the lines the lint exempts,
                             `Not tested:` and `Next step:`, and a table's header row, are exempt)
  measured-citation-missing  a claim tagged Measured or Tested cites a `path:line` that the staged
                             files do not have: no such file, a line past its end, or a commit
                             (the staged files have no history). The skill's way out is to fix the
                             citation or lower the tag, never to ship it
  measured-without-citation  a claim tagged Measured or Tested cites nothing at all: the skill
                             allows no such tag on what the citation check could not see

When more than one rule is broken a last line lists them all, because the runner keeps only the
last line of a validator. Exit 0 when none is broken, 1 otherwise.

How the reply is read. As the kit's own two scripts read it (`03-tools/lib/output_lint.py` and
`03-tools/lib/cite_check.py`): lines inside a ``` fence are outside the reply; a claim is one
bullet, one table row, or a run of consecutive prose lines; a reference is `path:line`,
`path:line-line`, either with an optional `@ sha`, or a URL; a tag is `[Measured]`, `[Tested]` or
their Spanish forms, with or without text after a colon or a space. The tag rule is the part of
COM-09 that finds an untagged claim, with the lint's own values in the answer key (the technical
headings, the tag vocabulary, the exempt markers: `03-tools/config/output-lint.json`); a reply with
no technical heading has no such claim, as in the lint. One difference, on purpose, in the two
citation rules: the citation check of the kit looks only under the `## Technical detail` heading,
and here every claim of the file is read, so a reply that drops or renames that heading cannot
carry an unchecked `[Measured]` out.

What it accepts. Either way the skill allows: the citation corrected to a line the staged file
has, or the tag lowered (Inferred, Assumed, Unknown) with the citation left as it was. A URL counts
as a reference in view. A reply reworded from top to bottom passes when its tagged claims hold.

What it cannot see. Whether a corrected line says what the claim says (line 2 passes as well as
line 23): existence is what the kit's script measures too, and the rest is the verifier's. Whether
the run measured anything at all: a run that lowers every tag without calling the lint passes this
file, and only the judge reads its answer. A reply that drops its tags together with the technical
heading: the lint has no tag rule for it either. Any other form rule of the lint (a tag outside the
vocabulary, a sentence too long, a filler): the long dash is the one the draft breaks, and the
untagged claim is the one a real run without the skill was seen to add.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

# The three patterns below are the ones of 03-tools/lib/cite_check.py and output_lint.py.
FILE_REF = re.compile(r"`?(?P<path>[\w./-]+\.[A-Za-z0-9]{1,8}):(?P<start>\d+)(?:-(?P<end>\d+))?`?(?:\s*@\s*(?P<sha>[0-9a-f]{7,40}))?")
URL = re.compile(r"https?://[^\s)>\]\"']+")
BULLET = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+")
HEADING = re.compile(r"^(#{1,6})\s")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}")
TAG = re.compile(r"\[([A-ZÁÉÍÓÚ][a-záéíóúñ]+)(?:[ :][^\]]*)?\]")


def lines_outside_fences(text: str) -> list[tuple[int, str]]:
    """(number, line) of every line that is not a ``` fence nor inside one; numbered from 1."""
    kept: list[tuple[int, str]] = []
    in_code = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            kept.append((number, line))
    return kept


def claims(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Claim units: each bullet and each table row is one; consecutive prose lines are one, numbered by the first."""
    units: list[tuple[int, str]] = []
    prose: list[tuple[int, str]] = []

    def close_prose() -> None:
        if prose:
            units.append((prose[0][0], " ".join(line for _number, line in prose)))
            prose.clear()

    for number, line in lines:
        if not line.strip() or HEADING.match(line) or TABLE_SEP.match(line):
            close_prose()
        elif BULLET.match(line) or line.lstrip().startswith("|"):
            close_prose()
            units.append((number, line))
        else:
            prose.append((number, line))
    close_prose()
    return units


def strip_markup(line: str) -> str:
    """The line without its bullet, heading mark, bold and backticks, as the lint strips it."""
    text = HEADING.sub("", BULLET.sub("", line)).replace("**", "").replace("`", "")
    return text.strip().lstrip("¡¿\"'«*_ ").strip()


def untagged_claims(lines: list[tuple[int, str]], key: dict) -> list[int]:
    """Line numbers of the claims under the technical heading that carry no tag of the vocabulary."""
    under = None
    for index, (_number, line) in enumerate(lines):
        if line.strip().lower() in key["technical_headings"]:
            under = lines[index + 1:]
            break
    if under is None:
        return []
    allowed = set(key["epistemic_tags"])
    untagged: list[int] = []
    header_row_seen = False
    for number, unit in claims(under):
        plain = strip_markup(unit)
        if plain.startswith("|") and not header_row_seen:
            header_row_seen = True  # the first row of a table is its header
            continue
        if any(match.group(1) in allowed for match in TAG.finditer(unit)):
            continue
        if not plain.startswith("|") and any(plain.lower().startswith(marker) for marker in key["untagged_markers"]):
            continue
        untagged.append(number)
    return untagged


def why_missing(ref: re.Match, staged: dict) -> str | None:
    """Why the staged files do not have what `ref` cites; None when they do."""
    if ref.group("sha"):
        return "the staged files have no commit to look it up in"
    path = ref.group("path")
    path = path[2:] if path.startswith("./") else path
    if path not in staged:
        return "no such file was staged"
    total = staged[path]["lines"]
    start = int(ref.group("start"))
    end = int(ref.group("end")) if ref.group("end") else start
    return None if 1 <= start <= end <= total else f"the staged file has {total} lines"


def cited(ref: re.Match) -> str:
    """The reference as the reply wrote it, without its backticks."""
    span = f"{ref.group('path')}:{ref.group('start')}" + (f"-{ref.group('end')}" if ref.group("end") else "")
    return span + (f" @ {ref.group('sha')}" if ref.group("sha") else "")


def broken_rules(reply: str, key: dict) -> list[tuple[str, str]]:
    broken: list[tuple[str, str]] = []
    lines = lines_outside_fences(reply)
    for number, line in lines:
        if key["long_dash"] in line:
            broken.append(("long-dash", f"line {number} carries a long dash (U+2014); COM-15 fails it and nothing ships with FAIL"))

    for number in untagged_claims(lines, key):
        broken.append(("untagged-claim",
                       f"line {number} of the technical layer carries no epistemic tag; COM-09 fails it and nothing ships with FAIL"))

    measured = re.compile(r"\[(" + "|".join(map(re.escape, key["measured_tags"])) + r")(?:[ :][^\]]*)?\]")
    for number, unit in claims(lines):
        tag = measured.search(unit)
        if not tag:
            continue
        refs = list(FILE_REF.finditer(unit))
        for ref in refs:
            why = why_missing(ref, key["staged_files"])
            if why:
                broken.append(("measured-citation-missing", f"line {number} cites {cited(ref)} under [{tag.group(1)}]; {why}"))
        if not refs and not URL.search(unit):
            broken.append(("measured-without-citation",
                           f"line {number} is tagged [{tag.group(1)}] and cites nothing that can be checked"))
    return broken


def main(workspace: str, testdata: str) -> int:
    key = json.loads((pathlib.Path(testdata) / "answer-key.json").read_text(encoding="utf-8"))
    saved = pathlib.Path(workspace) / key["saved_file"]
    try:
        reply = saved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = "is missing from the files the run left" if not saved.exists() else f"cannot be read: {exc}"
        print(f"output-missing: {key['saved_file']} {reason}", file=sys.stderr)
        return 1
    if not reply.strip():
        print(f"output-missing: {key['saved_file']} is empty", file=sys.stderr)
        return 1
    broken = broken_rules(reply, key)
    for rule, what in broken:
        print(f"{rule}: {what}", file=sys.stderr)
    if len(broken) > 1:
        print(f"{len(broken)} rules broken: {', '.join(rule for rule, _what in broken)}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
