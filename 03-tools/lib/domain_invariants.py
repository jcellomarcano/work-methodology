#!/usr/bin/env python3
"""Presence (not absence) of the mechanisms that sustain the domain
invariants (INV-NN, or the prefix declared by config/project.json:invariant_prefix),
measured by regex signals over <repo>'s .kt sources, configured in
config/invariants-checks.json.

This does NOT prove an invariant holds: it is a presence detector,
"does the mechanism that would sustain it even exist?", with file:line
evidence for a human to review. A signal that appears in no file is
reported with empty evidence, not as a script error: a negative finding
is still a finding.

Config (config/invariants-checks.json), see that file for the exact format
and config/examples/critical-flow/invariants-checks.json for a full example
instantiated over a critical-flow domain:
  {
    "invariants": {
      "<ID>": {
        "epistemic": "Medido",
        "note": "free text",
        "signals": [
          {"kind": "free label", "regex": "...", "scope": "all"|"money", "match": "line"|"filename"}
        ]
      }
    }
  }

`scope: "money"` restricts the scan to the paths listed in
config/project.json:money_paths (repo-relative prefixes); `scope: "all"`
(or absent) scans all production code (src/main/**) of the modules
declared in settings.gradle. `match: "filename"` searches the regex in
the file's name instead of in each content line.

Usage:
    lib/domain_invariants.py <repo> [--config <invariants-checks.json>] [--project-config <project.json>]

Writes out/<repo_sha>/domain-invariants.json and .md (the tools repo, not the
analyzed repo).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, repo_scan, toolenv  # noqa: E402

DEFAULT_INVARIANTS_CONFIG = TOOLS_ROOT / "config" / "invariants-checks.json"
DEFAULT_PROJECT_CONFIG = TOOLS_ROOT / "config" / "project.json"

BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def strip_comments(source: str) -> str:
    """Replaces `source`'s block comments ('/* ... */', KDoc ('/** ... */')
    included, since it is the same delimiter) and line comments ('//...')
    with spaces. Preserves every line break and the length of each
    commented line, so the line count does not change: the file:line the
    scanners report keeps pointing to the right spot after filtering."""

    def _blank(match: re.Match) -> str:
        return "".join(ch if ch == "\n" else " " for ch in match.group(0))

    without_blocks = BLOCK_COMMENT_RE.sub(_blank, source)
    return LINE_COMMENT_RE.sub(_blank, without_blocks)


def all_main_files(repo_root: Path) -> list[str]:
    modules = repo_scan.list_modules(repo_root)
    return [rel for _module, rel in repo_scan.kotlin_files(repo_root, modules, "main")]


def money_scoped(files: list[str], money_paths: list[str]) -> list[str]:
    prefixes = tuple(money_paths or ())
    if not prefixes:
        return []
    return [f for f in files if f.startswith(prefixes)]


def _lines(repo_root: Path, rel_path: str) -> list[str]:
    text = (repo_root / rel_path).read_text(encoding="utf-8", errors="replace")
    # Every scanner goes through here, so filtering comments in one place
    # is enough that no pattern counts a comment as real presence
    # (see strip_comments above).
    return strip_comments(text).splitlines()


def _scan_line_signal(repo_root: Path, files: list[str], kind: str, regex: re.Pattern) -> list[dict]:
    hits = []
    for rel_path in files:
        for i, line in enumerate(_lines(repo_root, rel_path), start=1):
            if regex.search(line):
                hits.append({"file": rel_path, "line": i, "kind": kind})
    hits.sort(key=lambda h: (h["file"], h["line"], h["kind"]))
    return hits


def _scan_filename_signal(files: list[str], kind: str, regex: re.Pattern) -> list[dict]:
    hits = [{"file": f, "kind": kind} for f in files if regex.search(Path(f).name)]
    hits.sort(key=lambda h: h["file"])
    return hits


def _file_set_for_scope(scope: str, all_files: list[str], money_files: list[str]) -> list[str]:
    return money_files if scope == "money" else all_files


def evaluate_signal(repo_root: Path, signal: dict, all_files: list[str], money_files: list[str]) -> list[dict]:
    kind = signal.get("kind") or signal["regex"]
    regex = re.compile(signal["regex"])
    scope = signal.get("scope", "all")
    match_mode = signal.get("match", "line")
    files = _file_set_for_scope(scope, all_files, money_files)
    if match_mode == "filename":
        return _scan_filename_signal(files, kind, regex)
    return _scan_line_signal(repo_root, files, kind, regex)


def build_domain_invariants(repo_root: Path, invariants_config: dict, money_paths: list[str]) -> dict:
    all_files = sorted(all_main_files(repo_root))
    money_files = money_scoped(all_files, money_paths)

    by_invariant: dict[str, dict] = {}
    for inv_id, spec in sorted(invariants_config.get("invariants", {}).items()):
        evidence: list[dict] = []
        for signal in spec.get("signals", []):
            evidence.extend(evaluate_signal(repo_root, signal, all_files, money_files))
        evidence.sort(key=lambda h: (h["file"], h.get("line", 0), h.get("kind", "")))
        by_invariant[inv_id] = {
            "epistemic": spec.get("epistemic", "Desconocido"),
            "note": spec.get("note", ""),
            "evidence": evidence,
        }

    return {
        "money_paths": sorted(money_paths or []),
        "files_scanned": len(all_files),
        "money_files_scanned": len(money_files),
        "by_invariant": by_invariant,
    }


def render_markdown(payload: dict) -> str:
    lines = ["# domain_invariants", "", f"repo_sha: `{payload['repo_sha']}`", ""]
    lines += ["## by_invariant", "", "| invariant | epistemic | evidence | note |", "|---|---|---|---|"]
    for key in sorted(payload["by_invariant"]):
        entry = payload["by_invariant"][key]
        lines.append(f"| {key} | {entry['epistemic']} | {len(entry['evidence'])} | {entry['note']} |")
    lines += ["", f"production files scanned: {payload['files_scanned']} "
                  f"(money files: {payload['money_files_scanned']})", ""]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("--config", default=None, help="config/invariants-checks.json")
    parser.add_argument("--project-config", default=None, help="config/project.json (for money_paths)")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    repo_sha = baseline.git_head_sha(repo_root)
    repo_dirty = baseline.is_repo_dirty(repo_root)
    versions = toolenv.tool_versions(TOOLS_ROOT)

    config_path = Path(args.config) if args.config else DEFAULT_INVARIANTS_CONFIG
    invariants_config = baseline.load_json(config_path) if config_path.exists() else {"invariants": {}}

    project_config_path = Path(args.project_config) if args.project_config else DEFAULT_PROJECT_CONFIG
    project_config = baseline.load_json(project_config_path) if project_config_path.exists() else {}
    money_paths = project_config.get("money_paths", [])

    content = build_domain_invariants(repo_root, invariants_config, money_paths)
    payload = baseline.base_envelope(TOOLS_ROOT, repo_sha, versions, repo_dirty)
    payload.update(content)

    out_dir = TOOLS_ROOT / "out" / repo_sha
    baseline.write_json(out_dir / "domain-invariants.json", payload)
    (out_dir / "domain-invariants.md").write_text(render_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
