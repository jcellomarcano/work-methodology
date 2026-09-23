#!/usr/bin/env python3
"""Writes the handoff between two roles as a numbered file of the round
(agent-protocol.md paragraph 4: "the script sets the sha; the agent
never types one"). Until now that script did not exist.

Usage:
    lib/handoff.py --repo <repo> --round-dir <dir> --from-role A --to-role B
        --topic <slug> --artifact <path> --summary "<one sentence>"
        [--residual-risk R]* [--truncated] [--not-covered X]*

Output: the written document (schemas/handoff.schema.json), on stdout, and
the NNN-<role>-<slug>.json file in the round directory. Exit 2 if the slug,
the roles, or the write guard do not pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, engram_bridge, findings_schema_validator, round_files  # noqa: E402


def build_handoff(repo: Path, round_dir: Path, from_role: str, to_role: str, artifact_path: Path,
                  summary: str, residual_risks: list[str], truncated: bool = False,
                  not_covered: list[str] | None = None, seq: int | None = None) -> dict:
    return {
        "seq": seq if seq is not None else round_files.next_seq(round_dir),
        "from_role": round_files.normalize_role(from_role),
        "to_role": round_files.normalize_role(to_role),
        "artifact_path": round_files.portable_path(Path(artifact_path), round_dir, repo),
        "repo_sha": baseline.git_head_sha(repo),
        "tools_sha": baseline.git_head_sha(TOOLS_ROOT),
        "summary": summary,
        "residual_risks": list(residual_risks),
        "truncated": truncated,
        "not_covered": list(not_covered or []),
    }


def write_handoff(repo: Path, round_dir: Path, from_role: str, to_role: str, topic: str, artifact_path: Path,
                  summary: str, residual_risks: list[str], truncated: bool = False,
                  not_covered: list[str] | None = None, project_config: dict | None = None) -> tuple[Path, dict]:
    if not round_files.SLUG_RE.match(topic):
        raise ValueError(f"topic is not a slug [a-z0-9-]: {topic}")
    round_dir = Path(round_dir)
    round_files.assert_write_allowed(round_dir / "x", repo, project_config)
    doc = build_handoff(repo, round_dir, from_role, to_role, artifact_path, summary, residual_risks, truncated, not_covered)
    result = findings_schema_validator.validate(doc, round_files.load_schema("handoff"))
    if result["verdict"] == "FAIL":
        raise ValueError("invalid handoff: " + "; ".join(result["errors"]))
    path = round_dir / round_files.numbered_name(doc["seq"], doc["from_role"], topic)
    baseline.write_json(path, doc)
    _remember(round_dir, doc, path)
    return path, doc


def _remember(round_dir: Path, doc: dict, path: Path) -> bool:
    """Indexes the handoff in engram under one key per round and role, so the
    key holds that role's latest word and the round directory holds them all."""
    round_name = round_dir.resolve().name
    body = "{} -> {}\nsummary: {}\nartifact: {}\nfile: {}".format(
        doc["from_role"], doc["to_role"], doc["summary"], doc["artifact_path"], path)
    return engram_bridge.save(f"handoff {round_name} {doc['from_role']}", body,
                              kind="context", topic_key=f"metodo/handoff/{round_name}/{doc['from_role']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--round-dir", required=True)
    parser.add_argument("--from-role", required=True)
    parser.add_argument("--to-role", required=True)
    parser.add_argument("--topic", required=True, help="slug [a-z0-9-]")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--residual-risk", action="append", default=[])
    parser.add_argument("--truncated", action="store_true")
    parser.add_argument("--not-covered", action="append", default=[])
    parser.add_argument("--config", default=None, help="config/project.json")
    args = parser.parse_args(argv)

    project_config = baseline.load_json(args.config) if args.config else None
    try:
        path, doc = write_handoff(
            Path(args.repo).resolve(), Path(args.round_dir), args.from_role, args.to_role, args.topic,
            Path(args.artifact), args.summary, args.residual_risk, args.truncated, args.not_covered, project_config,
        )
    except (ValueError, PermissionError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    doc["path"] = round_files.portable_path(path, Path(args.round_dir).parent)
    print(json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
