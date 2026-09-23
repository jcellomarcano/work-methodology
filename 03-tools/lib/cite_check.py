#!/usr/bin/env python3
"""Verifies that the technical layer's citations in a reply exist (rule COM-19).

`[Medido]` is a character, not a check: this script looks at whether what is cited exists. For each unit
of the technical layer (bullet, table row, or paragraph, as in output_lint.py) it looks for
`path:line[-line]` references (with an optional `@ sha`) and URLs, and returns per reference:

- OK: the file exists in `--repo` and the line falls inside it; with a sha, the file exists at that
  commit and the line falls inside that version (`git show sha:path`).
- MISSING: file absent, line out of range, or sha unknown in the repo. Fails.
- UNVERIFIED: URL without `--online`, or a file reference without `--repo`. Declared, does not fail.
- (with `--online`) OK_HTTP / MISSING_HTTP depending on the response of a HEAD request; the network use is declared.

A unit tagged `[Medido]` or `[Probado]` with no reference at all warns (`SIN_CITA`): it could be a pasted
command output, but nobody can check it from here. JSON output with sorted keys, no timestamps or
absolute paths, with `tool_sha`. Exit 1 if there is any MISSING.

Usage:
    lib/cite_check.py reply.md [--repo <path>] [--online]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import output_lint  # noqa: E402

_FILE_REF = re.compile(r"`?(?P<path>[\w./-]+\.[A-Za-z0-9]{1,8}):(?P<start>\d+)(?:-(?P<end>\d+))?`?(?:\s*@\s*(?P<sha>[0-9a-f]{7,40}))?")
_URL = re.compile(r"https?://[^\s)>\]\"']+")
_TAGGED_MEASURED = re.compile(r"\[(Medido|Probado)(?:[ :][^\]]*)?\]")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _line_count(repo: Path, rel: str, sha: str | None) -> int | None:
    if sha:
        proc = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:{rel}"], capture_output=True, text=True, errors="replace")
        if proc.returncode != 0:
            return None
        return proc.stdout.count("\n") + (0 if proc.stdout.endswith("\n") or not proc.stdout else 1)
    path = repo / rel
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return sum(1 for _ in fh)


def _check_file_ref(repo: Path | None, ref: dict) -> str:
    if repo is None:
        return "UNVERIFIED"
    total = _line_count(repo, ref["path"], ref["sha"])
    if total is None:
        return "MISSING"
    end = ref["end"] or ref["start"]
    return "OK" if 1 <= ref["start"] <= end <= total else "MISSING"


def _check_url(url: str, online: bool) -> str:
    if not online:
        return "UNVERIFIED"
    try:
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "cite_check"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return "OK_HTTP" if response.status < 400 else "MISSING_HTTP"
    except Exception:
        return "MISSING_HTTP"


def check(text: str, config: dict, repo: Path | None = None, online: bool = False) -> dict:
    lines = text.splitlines()
    _, technical, has_technical, _ = output_lint.split_layers(lines, config["technical_headings"])
    refs: list[dict] = []
    uncited: list[dict] = []
    if has_technical:
        for number, unit in output_lint._units(technical):
            found = 0
            for m in _FILE_REF.finditer(unit):
                found += 1
                ref = {"end": int(m.group("end")) if m.group("end") else None, "kind": "file", "line": number,
                       "path": m.group("path"), "sha": m.group("sha"), "start": int(m.group("start"))}
                ref["status"] = _check_file_ref(repo, ref)
                refs.append(ref)
            for url in _URL.findall(unit):
                found += 1
                refs.append({"kind": "url", "line": number, "status": _check_url(url, online), "url": url})
            if found == 0 and _TAGGED_MEASURED.search(unit):
                uncited.append(output_lint._evidence(number, unit))
    refs.sort(key=lambda r: (r["line"], r.get("path", ""), r.get("url", "")))
    statuses = [r["status"] for r in refs]
    summary = {s: statuses.count(s) for s in ("OK", "OK_HTTP", "MISSING", "MISSING_HTTP", "UNVERIFIED")}
    summary["SIN_CITA"] = len(uncited)
    missing = summary["MISSING"] + summary["MISSING_HTTP"]
    return {
        "online": online,
        "refs": refs,
        "repo_given": repo is not None,
        "summary": summary,
        "technical_heading": has_technical,
        "uncited_measured": uncited,
        "verdict": "FAIL" if missing else ("WARN" if uncited or summary["UNVERIFIED"] else "PASS"),
    }


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent.parent / "config"
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="markdown file with the reply, or - for stdin")
    parser.add_argument("--repo", help="repo where path:line and path:line @ sha are resolved")
    parser.add_argument("--online", action="store_true", help="check URLs with a HEAD request (declared in the output)")
    parser.add_argument("--config", default=str(here / "output-lint.json"))
    args = parser.parse_args(argv)

    text = sys.stdin.read() if args.path == "-" else Path(args.path).read_text(encoding="utf-8")
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    result = check(text, config, Path(args.repo).resolve() if args.repo else None, args.online)
    result["tool_sha"] = _sha(Path(__file__).resolve())
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    if result["verdict"] == "FAIL":
        for ref in result["refs"]:
            if ref["status"].startswith("MISSING"):
                print(f"MISSING line {ref['line']}: {ref.get('path') or ref.get('url')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
