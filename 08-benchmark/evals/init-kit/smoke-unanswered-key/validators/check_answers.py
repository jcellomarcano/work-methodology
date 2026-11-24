#!/usr/bin/env python3
"""Validator of init-kit/smoke-unanswered-key: answers.json holds what the owner answered and nothing else.

Called as `check_answers.py WORKSPACE TESTDATA`. The case stages `interview-notes.md`: the owner's
answers to nine setup questions for a repo. Four of them are answers the kit's `--answers` accepts
(the property order, the critical paths, the ticket keys and the language); one it accepts was not
answered (the critical properties: "not sure yet"); the other four are things `--answers` does not
take (the runtime and the audit folder, which are options of the command, and the reviewers and
the CI, which the kit does not ask for). The skill's rules for the file
(`02-skills/init-kit/SKILL.md`, step 2 and "What the model may add") are: collect only what
`--answers` accepts, never an unconfirmed value, and a key left out stays with detection and
returns as a pending human step. This script reads the file the run saved and the answer key,
`answer-key.json`, nothing else, and needs only the standard library.

One line on stderr per broken rule, each starting with the rule's name:

  output-missing      answers.json is not among the files the run left, or is not readable
  not-a-json-object   it is not JSON, or its top level is not an object
  unknown-key         it holds a key `--answers` does not accept
  wrong-type          a list key is not a list of non-empty strings, or the language is not one
  unconfirmed-key     it holds the key the owner did not answer
  unconfirmed-value   an answered key holds a value the owner did not give
  order-changed       the property order is not in the order the owner gave
  answer-missing      an answered key, or one of the values the owner gave for it, is not in the file

When more than one rule is broken a last line lists them all, because the runner keeps only the
last line of a validator. Exit 0 when none is broken, 1 otherwise.

Where each rule comes from. The first three after `output-missing` are the checks the kit's own
script makes on `--answers` (`03-tools/bin/adopt.sh`, the block under "answers"), with its words:
a file this validator rejects for them is a file `init.sh` would stop on with exit 2. The accepted
keys, and the old key name the script still takes (`money_paths` for `critical_paths`), are in the
answer key as the script has them. The other four compare the file with what the owner wrote in
the staged notes, copied into the answer key (`confirmed`, `not_answered`). The key the owner did
not answer breaks its rule whatever it holds, an empty list too: the script accepts an empty list,
and it would replace what detection finds with nothing, which nobody confirmed.

How a value is compared. Without letter case and without spaces, hyphens and underscores, so
"Data integrity", "data-integrity" and "data_integrity" are one value. A path also loses a leading
"./" and a trailing "/", "/*" or "/**", so "src/payments", "src/payments/" and "src/payments/**"
are one path. The order is checked only on the values the owner gave, so a value that is missing
or was added breaks its own rule and not this one too.

What the rules cannot see. Whether the run asked the owner about the unanswered key, showed the
command and waited before running it, or put the runtime and the audit folder on the command:
those are in the answer, which the judge reads. A value the owner gave, written with other words
("integrity of data"), reads as a value the owner did not give plus one that is missing.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

LOOSE = re.compile(r"[\s\-_]+")


def same(value: str, a_path: bool) -> str:
    """The form two spellings of one value share (see "How a value is compared")."""
    value = value.strip()
    if a_path:
        value = re.sub(r"^\./", "", value)
        value = re.sub(r"/(\*{1,2})?$", "", value)
    return LOOSE.sub("", value).casefold()


def well_typed(key: str, value: object, list_keys: list[str]) -> bool:
    if key in list_keys:
        return isinstance(value, list) and all(isinstance(item, str) and item for item in value)
    return isinstance(value, str) and bool(value)


def broken_rules(raw: str, key: dict) -> list[tuple[str, str]]:
    name = key["saved_file"]
    try:
        answers = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [("not-a-json-object", f"{name} is not valid JSON ({exc.msg})")]
    if not isinstance(answers, dict):
        return [("not-a-json-object", f"{name} must be a JSON object")]
    for old, new in key["renamed_keys"].items():
        if old in answers:
            answers.setdefault(new, answers.pop(old))

    broken: list[tuple[str, str]] = []
    list_keys, string_keys = key["accepted_list_keys"], key["accepted_string_keys"]
    accepted = sorted([*list_keys, *string_keys])
    unknown = sorted(set(answers) - set(accepted))
    if unknown:
        broken.append(("unknown-key", f"unknown keys {unknown}; accepted: {accepted}"))
    typed = {}
    for field in accepted:
        if field not in answers:
            continue
        if well_typed(field, answers[field], list_keys):
            typed[field] = answers[field]
        else:
            kind = "a list of non-empty strings" if field in list_keys else "a non-empty string"
            broken.append(("wrong-type", f"{field} must be {kind}"))

    for field in key["not_answered"]:
        if field in answers:
            broken.append(("unconfirmed-key", f"{field} is in the file; the owner did not answer it, "
                                              f"so it stays out and returns as a pending step"))

    for field, gave in key["confirmed"].items():
        if field not in answers:
            broken.append(("answer-missing", f"{field} is not in the file; the owner answered it"))
            continue
        if field not in typed:
            continue  # already reported as wrong-type
        a_path = "path" in field
        wrote = typed[field] if isinstance(typed[field], list) else [typed[field]]
        given = gave if isinstance(gave, list) else [gave]
        wrote_as, given_as = [same(value, a_path) for value in wrote], [same(value, a_path) for value in given]
        for value, value_as in zip(wrote, wrote_as):
            if value_as not in given_as:
                broken.append(("unconfirmed-value", f"{field} holds {value!r}; the owner did not give it"))
        for value, value_as in zip(given, given_as):
            if value_as not in wrote_as:
                broken.append(("answer-missing", f"{field} lacks {value!r}; the owner gave it"))
        kept = [value_as for value_as in wrote_as if value_as in given_as]
        if field == "property_order" and kept != [value_as for value_as in given_as if value_as in kept]:
            broken.append(("order-changed", f"{field} is not in the order the owner gave"))
    return broken


def main(workspace: str, testdata: str) -> int:
    key = json.loads((pathlib.Path(testdata) / "answer-key.json").read_text(encoding="utf-8"))
    saved = pathlib.Path(workspace) / key["saved_file"]
    try:
        raw = saved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        reason = "is missing from the files the run left" if not saved.exists() else f"cannot be read: {exc}"
        print(f"output-missing: {key['saved_file']} {reason}", file=sys.stderr)
        return 1
    broken = broken_rules(raw, key)
    for rule, what in broken:
        print(f"{rule}: {what}", file=sys.stderr)
    if len(broken) > 1:
        rules = list(dict.fromkeys(rule for rule, _what in broken))
        print(f"{len(rules)} rule{'s' if len(rules) > 1 else ''} broken: {', '.join(rules)}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
