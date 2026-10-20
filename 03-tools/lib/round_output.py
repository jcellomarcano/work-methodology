#!/usr/bin/env python3
"""Validates a role's output document against its schema and, only if it
passes, writes it as NNN-<role>-<schema>.json in the round directory. It
is the only way an agent with no Bash or Write has of leaving its output
on disk: the output_write MCP tool wraps this script.

Usage:
    lib/round_output.py --round-dir <dir> --role <role> [--schema <name>] (--document <path> | -)

Without --schema, the role's schema is used (round_files.ROLE_SCHEMA).
Output: {verdict, errors, path, schema, report_tokens, warnings} on stdout.
Exit 1 on FAIL (nothing is written), 2 on usage error or write guard.

The document is the subagent's report: over the D9 cap
(findings_schema_validator.REPORT_CAP_TOKENS, ceil(chars / 4) of the
document as sent) it is still written, with a `report-over-cap` warning
naming the fix. A context_tokens_used above the role contract's
max_context_tokens adds a `context-over-cap` warning (a measurement, never a
FAIL). Warnings never change the verdict or the exit code.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, findings_schema_validator, round_files  # noqa: E402


def _max_context_tokens(role: str, repo: Path | None):
    """The role contract's max_context_tokens: the analyzed repo's installed
    contract first, then the kit's, the same order the hooks use."""
    candidates = [Path(repo) / ".claude" / "agents" / f"{role}.contract.json"] if repo is not None else []
    candidates.append(TOOLS_ROOT.parent / "01-roles" / "agents" / f"{role}.contract.json")
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8")).get("max_context_tokens")
            except (OSError, json.JSONDecodeError, AttributeError):
                return None
    return None


def _warnings(role: str, document: dict, tokens: int, repo: Path | None) -> list[str]:
    fsv = findings_schema_validator
    warnings = []
    if tokens > fsv.REPORT_CAP_TOKENS:
        warnings.append(f"report-over-cap: {tokens} tokens > {fsv.REPORT_CAP_TOKENS}; {fsv.REPORT_CAP_FIX}")
    cap = _max_context_tokens(role, repo)
    used = fsv.context_over_cap(document, cap)
    if used is not None:
        warnings.append(f"context-over-cap: context_tokens_used {used} > max_context_tokens {cap}")
    return warnings


def write_output(round_dir: Path, role: str, document: dict, schema_name: str | None = None,
                 repo: Path | None = None, project_config: dict | None = None) -> dict:
    role = round_files.normalize_role(role)
    schema_name = schema_name or round_files.ROLE_SCHEMA[role]
    round_dir = Path(round_dir)
    round_files.assert_write_allowed(round_dir / "x", repo, project_config)
    result = findings_schema_validator.validate(document, round_files.load_schema(schema_name))
    tokens = findings_schema_validator.report_tokens(json.dumps(document, ensure_ascii=False))
    warnings = _warnings(role, document, tokens, repo)
    if result["verdict"] == "FAIL":
        return {"verdict": "FAIL", "errors": result["errors"], "path": None, "schema": schema_name,
                "report_tokens": tokens, "warnings": warnings}
    path = round_dir / round_files.numbered_name(round_files.next_seq(round_dir), role, schema_name)
    baseline.write_json(path, document)
    return {
        "verdict": result["verdict"],
        "errors": [],
        "path": round_files.portable_path(path, round_dir.parent),
        "schema": schema_name,
        "report_tokens": tokens,
        "warnings": warnings,
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
