#!/usr/bin/env python3
"""Hand-written JSON Schema validator (Python 3.11 stdlib, no dependencies)
for the v3 methodology documents (findings/blindspots/verdict/
claims/brief/handoff) in schemas/*.schema.json.

Only understands the subset those files use: "type", "required",
"properties", "items", "enum" and "additionalProperties": false (for the
MCP tools' input schemas, where a mistyped field has to fail before the
script runs). It is not a generic JSON Schema engine, and does not aim
to be.

Adversarial round: findings/blindspots/verdict/claims can declare
`truncated: true` (with `not_covered: [...]`) when the agent ran out of
budget mid-round. A truncated document that otherwise validates clean is
not "PASS" (that would read it as a complete round it never was) nor
"FAIL" (it is not broken, it is incomplete): it comes out "INCOMPLETE".
A document with shape errors is still FAIL no matter what `truncated`
says: incomplete is not the same as invalid.

Usage:
    lib/findings_schema_validator.py <json> --schema schemas/<name>.schema.json

Output: JSON on stdout with {verdict, errors}. Exit code 1 on FAIL (never
on INCOMPLETE: an incomplete round does not block the pipeline, it is
only flagged).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _type_ok(value, expected_type: str) -> bool:
    py_type = _TYPE_MAP[expected_type]
    if expected_type in ("integer", "number") and isinstance(value, bool):
        return False  # bool is a subclass of int in Python; does not count as a number
    return isinstance(value, py_type)


def _matching_type(value, expected) -> str | None:
    """`expected` is a string ('object') or a list of alternatives
    (['string', 'integer'], for a field whose real shape varies: 'round'
    comes out as an integer in some rounds and as a label in others).
    Returns the first candidate type `value` satisfies, or None if it
    satisfies none."""
    candidates = expected if isinstance(expected, list) else [expected]
    for candidate in candidates:
        if _type_ok(value, candidate):
            return candidate
    return None


def validate_value(value, schema: dict, path: str) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    matched_type = None

    if expected_type is not None:
        matched_type = _matching_type(value, expected_type)
        if matched_type is None:
            actual = type(value).__name__
            expected_desc = expected_type if isinstance(expected_type, str) else " or ".join(expected_type)
            errors.append(f"{path}: expected type '{expected_desc}', got '{actual}'")
            return errors  # with the base type broken, going deeper adds nothing

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: '{value}' is not in {schema['enum']}")

    if matched_type == "object":
        for required_key in schema.get("required", []):
            if required_key not in value:
                errors.append(f"{path}: missing required field '{required_key}'")
        for key, subschema in schema.get("properties", {}).items():
            if key in value:
                errors.extend(validate_value(value[key], subschema, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            declared = set(schema.get("properties", {}))
            for key in sorted(value):
                if key not in declared:
                    errors.append(f"{path}: undeclared field '{key}'")

    if matched_type == "array":
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, item in enumerate(value):
                errors.extend(validate_value(item, item_schema, f"{path}[{i}]"))

    return errors


def validate(document, schema: dict) -> dict:
    errors = sorted(validate_value(document, schema, "$"))
    truncated = isinstance(document, dict) and document.get("truncated") is True
    supports_truncated = "truncated" in schema.get("properties", {})

    if errors:
        verdict = "FAIL"
    elif truncated and supports_truncated:
        verdict = "INCOMPLETE"
    else:
        verdict = "PASS"

    return {"verdict": verdict, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", help="path to the JSON to validate")
    parser.add_argument("--schema", required=True, help="path to schemas/<name>.schema.json")
    args = parser.parse_args(argv)

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    document = json.loads(Path(args.document).read_text(encoding="utf-8"))

    result = validate(document, schema)
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))

    return 1 if result["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
