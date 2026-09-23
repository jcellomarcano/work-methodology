#!/usr/bin/env python3
"""Verifies that an agent moved within its role contract.

Compares the files it actually changed (a commit range, or a worktree's
dirty working tree) against <agent>.contract.json: FAIL if it touches
anything in `forbidden_paths`, or if the contract/--scope-glob declare a
`may_write` and the change falls outside that list. The project's shared
build files (config/project.json: shared_build_files) and any path under
`.claude/` are ALWAYS forbidden, whether the contract says so or not: no
role edits them, not even the most permissive one. Without
config/project.json available, a reasonable default list is used (the 5
Gradle build files) so the validator still works outside an adapted
project.

Usage:
    lib/role_contract_validator.py --contract <agent>.contract.json \\
        --repo <repo> (--range A..B | --worktree <dir>) [--scope-glob G ...] \\
        [--config <project.json>]

Output: JSON on stdout with {agent, changed_paths, forbidden_hits,
outside_allowlist, verdict}. Exit code 1 on FAIL.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline  # noqa: E402

DEFAULT_PROJECT_CONFIG = TOOLS_ROOT / "config" / "project.json"

# Used when there is no config/project.json (or it does not declare
# shared_build_files): the most common Gradle build layout, so the
# validator is never left with no default lock at all.
DEFAULT_SHARED_BUILD_FILES = (
    "settings.gradle",
    "build.gradle",
    "gradle.properties",
    "gradle/libs.versions.toml",
    "app/build.gradle",
)
ALWAYS_FORBIDDEN_CLAUDE_GLOBS = (".claude/**", "**/.claude/**")


def load_project_config(path: Path | None) -> dict:
    config_path = path or DEFAULT_PROJECT_CONFIG
    if not config_path.exists():
        return {}
    return baseline.load_json(config_path)


def always_forbidden_patterns(project_config: dict | None = None) -> list[str]:
    """shared_build_files from config/project.json (or the Gradle default
    if there is no config, or the field is empty) + the .claude/ globs,
    always, no matter what the role contract says."""
    shared_build_files = None
    if project_config:
        shared_build_files = project_config.get("shared_build_files")
    if not shared_build_files:
        shared_build_files = DEFAULT_SHARED_BUILD_FILES
    return list(shared_build_files) + list(ALWAYS_FORBIDDEN_CLAUDE_GLOBS)


def _match_any(path: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return pattern
    return None


def changed_paths_from_range(repo_root: Path, range_arg: str) -> list[str]:
    """git diff treats 'A..B' the same as 'A B' (unlike git log): it is a
    comparison of two trees, not a walk over commits."""
    out = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-only", range_arg],
        check=True, capture_output=True, text=True,
    )
    return sorted({p for p in out.stdout.splitlines() if p.strip()})


def changed_paths_from_worktree(worktree_dir: Path) -> list[str]:
    # --untracked-files=all: without this, a whole new directory comes out
    # as a single "?? dirname/" line and no standalone file pattern matches it.
    out = subprocess.run(
        ["git", "-C", str(worktree_dir), "status", "--porcelain", "--untracked-files=all"],
        check=True, capture_output=True, text=True,
    )
    paths = set()
    for line in out.stdout.splitlines():
        if line.strip():
            paths.add(baseline._status_line_path(line))
    return sorted(paths)


def evaluate(contract: dict, changed_paths: list[str], scope_globs: list[str], always_forbidden: list[str] | None = None) -> dict:
    if always_forbidden is None:
        always_forbidden = always_forbidden_patterns()
    forbidden_patterns = list(always_forbidden) + list(contract.get("forbidden_paths", []))
    allow_patterns = list(contract.get("may_write", [])) + list(scope_globs or [])
    allowlist_active = bool(allow_patterns)

    forbidden_hits = []
    outside_allowlist = []
    for path in changed_paths:
        hit_pattern = _match_any(path, forbidden_patterns)
        if hit_pattern is not None:
            forbidden_hits.append({"path": path, "pattern": hit_pattern})
            continue
        if allowlist_active and _match_any(path, allow_patterns) is None:
            outside_allowlist.append(path)

    verdict = "FAIL" if (forbidden_hits or outside_allowlist) else "PASS"
    return {
        "agent": contract.get("agent", "unknown"),
        "changed_paths": sorted(changed_paths),
        "forbidden_hits": sorted(forbidden_hits, key=lambda h: h["path"]),
        "outside_allowlist": sorted(outside_allowlist),
        "verdict": verdict,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--range", default=None, help="e.g. 'origin/develop..HEAD'")
    parser.add_argument("--worktree", default=None, help="directory of a worktree with uncommitted changes")
    parser.add_argument("--scope-glob", action="append", default=[], help="repeatable; added to the contract's may_write")
    parser.add_argument("--config", default=None, help="config/project.json (shared_build_files)")
    args = parser.parse_args(argv)

    if bool(args.range) == bool(args.worktree):
        parser.error("pass exactly one of --range or --worktree")

    contract = baseline.load_json(args.contract)
    repo_root = Path(args.repo).resolve()
    project_config = load_project_config(Path(args.config) if args.config else None)

    if args.range:
        changed_paths = changed_paths_from_range(repo_root, args.range)
    else:
        changed_paths = changed_paths_from_worktree(Path(args.worktree).resolve())

    result = evaluate(contract, changed_paths, args.scope_glob, always_forbidden_patterns(project_config))
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
