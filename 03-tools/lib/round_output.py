#!/usr/bin/env python3
"""Validates a role's output document against its schema and, only if it
passes, writes it as NNN-<role>-<schema>.json in the round directory. It
is the only way an agent with no Bash or Write has of leaving its output
on disk: the output_write MCP tool wraps this script.

Usage:
    lib/round_output.py --round-dir <dir> --role <role> [--schema <name>] (--document <path> | -)

Without --schema, the role's schema is used (round_files.ROLE_SCHEMA).
Output: {verdict, errors, path} on stdout. Exit 1 on FAIL (nothing is
written), 2 on usage error or write guard.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, findings_schema_validator, round_files  # noqa: E402


def write_output(round_dir: Path, role: str, document: dict, schema_name: str | None = None,
                 repo: Path | None = None, project_config: dict | None = None) -> dict:
    role = round_files.normalize_role(role)
    schema_name = schema_name or round_files.ROLE_SCHEMA[role]
    round_dir = Path(round_dir)
    round_files.assert_write_allowed(round_dir / "x", repo, project_config)
    result = findings_schema_validator.validate(document, round_files.load_schema(schema_name))
    if result["verdict"] == "FAIL":
        return {"verdict": "FAIL", "errors": result["errors"], "path": None, "schema": schema_name}
    path = round_dir / round_files.numbered_name(round_files.next_seq(round_dir), role, schema_name)
    baseline.write_json(path, document)
    return {
        "verdict": result["verdict"],
        "errors": [],
        "path": round_files.portable_path(path, round_dir.parent),
        "schema": schema_name,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round-dir", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--schema", default=None)
    parser.add_argument("--document", required=True, help="path to the JSON, or '-' for stdin")
    parser.add_argument("--repo", default=None, help="the analyzed repo: the round never lives inside it")
    parser.add_argument("--config", default=None, help="config/project.json")
    args = parser.parse_args(argv)

    raw = sys.stdin.read() if args.document == "-" else Path(args.document).read_text(encoding="utf-8")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"document is not JSON: {exc}"}), file=sys.stderr)
        return 2
    project_config = baseline.load_json(args.config) if args.config else None
    try:
        result = write_output(Path(args.round_dir), args.role, document, args.schema,
                              Path(args.repo).resolve() if args.repo else None, project_config)
    except (ValueError, PermissionError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    return 1 if result["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
