#!/usr/bin/env python3
"""Validator of change-card/smoke-missing-field: card-verdict.json says what the kit's validator says.

Called as `check_verdict.py WORKSPACE TESTDATA`. The answer key, `expected-verdict.json`, is what
`03-tools/lib/change_card_validator.py` prints for the staged card. Three keys decide: `verdict`,
`routing` and `fields_missing` (in any order), at the top level of the JSON object the run saved.
Exit 0 when the three match; 1 with one line on stderr when the file is missing, is not a JSON
object or holds another value.
"""
import json
import pathlib
import sys

DECIDING = ("verdict", "routing", "fields_missing")


def main(workspace: str, testdata: str) -> int:
    saved = pathlib.Path(workspace) / "card-verdict.json"
    if not saved.is_file():
        print("card-verdict.json is missing from the files the run left", file=sys.stderr)
        return 1
    try:
        got = json.loads(saved.read_text(encoding="utf-8"))
        expected = json.loads((pathlib.Path(testdata) / "expected-verdict.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"card-verdict.json or the answer key is not readable JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(got, dict):
        print(f"card-verdict.json must be a JSON object, got {type(got).__name__}", file=sys.stderr)
        return 1
    for key in DECIDING:
        ours, theirs = expected[key], got.get(key)
        if key == "fields_missing" and isinstance(theirs, list):
            ours, theirs = sorted(ours), sorted(map(str, theirs))
        if ours != theirs:
            print(f"card-verdict.json has {key} {got.get(key)!r}, the validator says {expected[key]!r}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
