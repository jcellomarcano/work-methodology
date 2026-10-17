#!/usr/bin/env python3
"""Delivery metrics from git history: commit shape, tests-with-code, lead time per merge.

Deterministic: same repository state, same bytes out. No author names, no
absolute paths, no diff content leave this script.

Usage:
  git_metrics.py --repo <path> [--repo <path> ...] [--since YYYY-MM-DD] --out git.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess
import sys

SCHEMA_VERSION = "1.0.0"
CONVENTIONAL = re.compile(r"^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([^)]+\))?!?: \S")
TEST_PATH = re.compile(r"(^|/)(test|tests|androidTest|__tests__|spec)(/|$)|(Test|Tests|Spec|_test)\.[a-z]+$")
DOC_PATH = re.compile(r"\.(md|rst|txt|adoc)$|(^|/)docs?/")
CODE_EXT = re.compile(r"\.(kt|kts|java|py|ts|tsx|js|jsx|go|rb|rs|swift|c|cc|cpp|h|cs|php|scala|sh)$")
SEP = "\x1f"


def _git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout


def _date(iso: str) -> str:
    return iso[:10]


def _parse_log(repo: pathlib.Path, since: str | None):
    """Yield commit dicts from `git log --numstat` over all refs reachable from HEAD."""
    fmt = SEP.join(["%H", "%P", "%cI", "%s"])
    args = ["log", "--first-parent" if False else "--all", "--numstat", "--no-renames",
            f"--format=%x00{fmt}"]
    if since:
        args.append(f"--since={since}")
    out = _git(repo, *args)
    for chunk in out.split("\x00")[1:]:
        lines = chunk.strip("\n").split("\n")
        head = lines[0].split(SEP)
        sha, parents, ciso, subject = head[0], head[1].split(), head[2], head[3]
        files = []
        for ln in lines[1:]:
            parts = ln.split("\t")
            if len(parts) != 3:
                continue
            add, rem, path = parts
            files.append((path, 0 if add == "-" else int(add), 0 if rem == "-" else int(rem)))
        yield {"sha": sha, "parents": parents, "ciso": ciso, "subject": subject, "files": files}


def _classify(commit: dict) -> dict:
    paths = [f[0] for f in commit["files"]]
    return {
        "sha": commit["sha"][:12],
        "date": _date(commit["ciso"]),
        "subject": commit["subject"][:120],
        "is_merge": len(commit["parents"]) > 1,
        "conventional": bool(CONVENTIONAL.match(commit["subject"])),
        "files": len(paths),
        "insertions": sum(f[1] for f in commit["files"]),
        "deletions": sum(f[2] for f in commit["files"]),
        "touches_tests": any(TEST_PATH.search(p) for p in paths),
        "touches_code": any(CODE_EXT.search(p) and not TEST_PATH.search(p) for p in paths),
        "touches_docs": any(DOC_PATH.search(p) for p in paths),
    }


def _merges(repo: pathlib.Path, since: str | None):
    """Lead time per merge commit on the first-parent line of HEAD."""
    args = ["log", "--first-parent", "--merges", f"--format=%H{SEP}%P{SEP}%cI{SEP}%s"]
    if since:
        args.append(f"--since={since}")
    merges = []
    for ln in _git(repo, *args).splitlines():
        sha, parents, ciso, subject = ln.split(SEP)
        p = parents.split()
        if len(p) < 2:
            continue
        rng = _git(repo, "log", "--format=%cI", f"{p[0]}..{p[1]}").split()
        if not rng:
            continue
        first = min(dt.datetime.fromisoformat(x) for x in rng)
        merged = dt.datetime.fromisoformat(ciso)
        merges.append({"sha": sha[:12], "date": _date(ciso), "subject": subject[:120],
                       "commits": len(rng),
                       "lead_time_days": round((merged - first).total_seconds() / 86400, 3)})
    return merges


def analyze_repo(repo: pathlib.Path, since: str | None = None) -> dict:
    commits = [_classify(c) for c in _parse_log(repo, since)]
    commits.sort(key=lambda c: (c["date"], c["sha"]))
    non_merge = [c for c in commits if not c["is_merge"]]
    code = [c for c in non_merge if c["touches_code"]]
    dates = [c["date"] for c in commits]
    by_month = {}
    for c in non_merge:
        m = by_month.setdefault(c["date"][:7], {"commits": 0, "insertions": 0, "deletions": 0,
                                                  "conventional": 0, "code_with_tests": 0, "code": 0})
        m["commits"] += 1
        m["insertions"] += c["insertions"]
        m["deletions"] += c["deletions"]
        m["conventional"] += int(c["conventional"])
        if c["touches_code"]:
            m["code"] += 1
            m["code_with_tests"] += int(c["touches_tests"])
    return {
        "name": repo.name,
        "head": _git(repo, "rev-parse", "HEAD").strip()[:12],
        "commits": commits,
        "merges": _merges(repo, since),
        "by_month": dict(sorted(by_month.items())),
        "summary": {
            "commits": len(non_merge),
            "merges": len(commits) - len(non_merge),
            "conventional_rate": round(sum(c["conventional"] for c in non_merge) / len(non_merge), 6) if non_merge else None,
            "code_commits": len(code),
            "code_commits_with_tests_rate": round(sum(c["touches_tests"] for c in code) / len(code), 6) if code else None,
            "first_date": min(dates) if dates else None,
            "last_date": max(dates) if dates else None,
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", action="append", required=True)
    ap.add_argument("--since", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    repos = []
    failures = []
    for r in args.repo:
        path = pathlib.Path(r).expanduser()
        try:
            repos.append(analyze_repo(path, args.since))
        except (subprocess.CalledProcessError, OSError, ValueError) as exc:
            failures.append({"repo": path.name, "error": repr(exc)[:200]})
    repos.sort(key=lambda x: x["name"])
    payload = {"schema_version": SCHEMA_VERSION,
               "tool_sha256": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
               "since": args.since, "repos": repos, "failures": failures}
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"repos": len(repos), "failures": len(failures), "out": str(out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
