#!/usr/bin/env python3
"""Which changes are really the PR's and which are noise from the base branch (step 1 of review-comment).

Compares two git diffs:
- `base...head` (three dots): what the PR branch added since the merge-base. That IS the PR.
- `base..head` (two dots): what differs between the two tips. Includes what the base advanced
  after branching; those files are NOT the PR's, and a reviewer who comments on them wastes
  time (or blames the wrong person).

JSON output with sorted keys: `merge_base`, `commits` (the PR's, short sha and subject),
`pr_files` (path, added and removed lines, status), `base_drift_files` (appear in two dots
and not in three: base noise), `mixed_files` (in both: the PR touches them and the base also
moved them; that is where the web diff can mislead), `tool_sha`, `repo_sha`, `repo_dirty`. No
timestamps or absolute paths. Same repo, same shas, same output. Exit 0 whenever git
responds: the script reports, it does not judge.

Usage:
    lib/pr_scope.py --repo <repo> --base <branch-or-sha> --head <branch-or-sha>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def _numstat(repo: Path, rev_range: str) -> dict:
    files: dict = {}
    for line in _git(repo, "diff", "--numstat", rev_range).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        files[path] = {"added": int(added) if added.isdigit() else 0, "removed": int(removed) if removed.isdigit() else 0}
    for line in _git(repo, "diff", "--name-status", rev_range).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            path = parts[-1]
            files.setdefault(path, {"added": 0, "removed": 0})["status"] = parts[0][0]
    return files


def scope(repo: Path, base: str, head: str) -> dict:
    merge_base = _git(repo, "merge-base", base, head).strip()
    three = _numstat(repo, f"{base}...{head}")
    two = _numstat(repo, f"{base}..{head}")
    commits = []
    for line in _git(repo, "log", "--format=%h%x09%s", f"{base}..{head}").splitlines():
        sha, _, subject = line.partition("\t")
        commits.append({"sha": sha, "subject": subject})
    pr_files = [{"path": p, **three[p]} for p in sorted(three)]
    drift = sorted(p for p in two if p not in three)
    mixed = sorted(p for p in two if p in three and two[p] != three[p])
    head_sha = _git(repo, "rev-parse", "--short=12", head).strip()
    dirty = bool(_git(repo, "status", "--porcelain").strip())
    return {
        "base": base,
        "base_drift_files": drift,
        "commits": commits,
        "head": head,
        "merge_base": merge_base[:12],
        "mixed_files": mixed,
        "pr_files": pr_files,
        "repo_dirty": dirty,
        "repo_sha": head_sha,
        "summary": {"base_drift": len(drift), "commits": len(commits), "mixed": len(mixed), "pr_files": len(pr_files)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    try:
        result = scope(Path(args.repo).resolve(), args.base, args.head)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result["tool_sha"] = hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()[:12]
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
