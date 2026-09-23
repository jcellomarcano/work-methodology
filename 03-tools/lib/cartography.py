#!/usr/bin/env python3
"""Assembles out/<repo_sha>/cartography.json from what shape_metrics.py and
dep_boundaries.py already wrote, plus the hotspots and the merge-tree
simulation that bin/cartography.sh computed by invoking git directly (git
is simpler to invoke from bash than to reimplement here, and this module
does not reimplement that part: it only assembles and writes).

Usage (normally invoked by bin/cartography.sh, not by hand):
    lib/cartography.py <repo> --hotspots-file <tsv> --conflicts-file <txt> \\
        --target-branch origin/develop [--merge-tree-unavailable]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, toolenv  # noqa: E402

HOTSPOT_LINE_RE = re.compile(r"^\s*(\d+)\s+(.+)$")
HOTSPOTS_LIMIT = 30


def parse_hotspots(path: Path, limit: int = HOTSPOTS_LIMIT) -> list[dict]:
    """Expects `sort | uniq -c` lines ('  <count> <path>'). Deterministic
    order: descending count and, on ties, ascending path: never the
    filesystem's order of appearance."""
    if not path.exists():
        return []
    rows: list[tuple[int, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HOTSPOT_LINE_RE.match(line)
        if match:
            rows.append((int(match.group(1)), match.group(2).strip()))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return [{"path": p, "touches": c} for c, p in rows[:limit]]


def parse_conflicts(path: Path) -> list[str]:
    if not path.exists():
        return []
    return sorted({line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()})


def build_cartography(
    repo_root: Path,
    repo_sha: str,
    hotspots: list[dict],
    conflicted_paths: list[str],
    target_branch: str,
    merge_tree_available: bool,
) -> dict:
    out_dir = TOOLS_ROOT / "out" / repo_sha
    metrics = baseline.load_json(out_dir / "metrics.json")
    deps = baseline.load_json(out_dir / "deps.json")

    shape_summary = {
        "files_count": metrics["totals"]["files_count"],
        "loc": metrics["totals"]["loc"],
        "files_over_500": metrics["totals"]["files_over_500"],
        "fun_count": metrics["totals"]["fun_count"],
    }
    dep_summary = {
        "violations_total": len(deps["violations"]),
        "cycle_candidates": {k: v["count"] for k, v in deps["cycle_candidates"].items()},
        "adapter_law_candidates_total": len(deps["adapter_law_candidates"]),
    }

    return {
        "shape_summary": shape_summary,
        "dep_summary": dep_summary,
        "hotspots": hotspots,
        "merge_conflict_simulation": {
            "target_branch": target_branch,
            "available": merge_tree_available,
            "conflicted_paths": conflicted_paths,
        },
    }


def render_markdown(payload: dict) -> str:
    lines = ["# cartography", "", f"repo_sha: `{payload['repo_sha']}`", ""]

    lines += ["## Shape (summary)", "", "| metric | value |", "|---|---|"]
    for key in sorted(payload["shape_summary"]):
        lines.append(f"| {key} | {payload['shape_summary'][key]} |")

    lines += ["", "## Boundaries (summary)", "", "| metric | value |", "|---|---|"]
    lines.append(f"| violations_total | {payload['dep_summary']['violations_total']} |")
    lines.append(f"| adapter_law_candidates_total | {payload['dep_summary']['adapter_law_candidates_total']} |")
    for key, count in sorted(payload["dep_summary"]["cycle_candidates"].items()):
        lines.append(f"| cycle: {key} | {count} |")

    lines += ["", f"## Hotspots (last 90 days, top {HOTSPOTS_LIMIT})", "", "| file | touches |", "|---|---|"]
    for h in payload["hotspots"]:
        lines.append(f"| {h['path']} | {h['touches']} |")

    mt = payload["merge_conflict_simulation"]
    lines += ["", f"## Merge simulation vs {mt['target_branch']}", ""]
    if not mt["available"]:
        lines.append(f"Could not simulate: `{mt['target_branch']}` does not exist in this checkout.")
    elif not mt["conflicted_paths"]:
        lines.append("No conflicts.")
    else:
        lines += ["| conflicted file |", "|---|"]
        for p in mt["conflicted_paths"]:
            lines.append(f"| {p} |")

    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("--hotspots-file", required=True)
    parser.add_argument("--conflicts-file", required=True)
    parser.add_argument("--target-branch", default="origin/develop")
    parser.add_argument("--merge-tree-unavailable", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    repo_sha = baseline.git_head_sha(repo_root)
    repo_dirty = baseline.is_repo_dirty(repo_root)
    versions = toolenv.tool_versions(TOOLS_ROOT)

    hotspots = parse_hotspots(Path(args.hotspots_file))
    conflicted_paths = parse_conflicts(Path(args.conflicts_file))
    content = build_cartography(
        repo_root, repo_sha, hotspots, conflicted_paths, args.target_branch,
        merge_tree_available=not args.merge_tree_unavailable,
    )

    payload = baseline.base_envelope(TOOLS_ROOT, repo_sha, versions, repo_dirty)
    payload.update(content)

    out_dir = TOOLS_ROOT / "out" / repo_sha
    baseline.write_json(out_dir / "cartography.json", payload)
    (out_dir / "cartography.md").write_text(render_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
