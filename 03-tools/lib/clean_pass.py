#!/usr/bin/env python3
"""Assembles out/<repo_sha>/clean-pass.json: the UNION of what shape_metrics,
duplication_cpd, and dep_boundaries already wrote out (bin/clean-pass.sh runs
those three before calling this). Each row carries its rule; there are no
proposals: deciding what to do with each row is the skill's job, not this
script's.

"Functions over 50 lines" comes out at FILE level, not function level: the
shape_metrics.py histogram counts how many functions fall in each bucket
per file, but does not store which function or on what line (it is
deliberately an aggregate count, not an AST). A file with >0 in the 51-100
or 101+ bucket gets flagged; the exact function name has to be found by
hand.

Usage:
    lib/clean_pass.py <repo>

Writes out/<repo_sha>/clean-pass.json and .md (the tools repo, not the
analyzed repo).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, toolenv  # noqa: E402

LOC_OVER_THRESHOLD = 500
HOTSPOT_TOP_N = 20


def _files_over_loc(metrics: dict, threshold: int) -> list[dict]:
    over = [f for f in metrics["files"] if f["loc"] > threshold]
    over.sort(key=lambda f: (-f["loc"], f["path"]))
    return [{"rule": "files-over-500", "file": f["path"], "detail": f"loc={f['loc']}"} for f in over]


def _long_functions_by_file(metrics: dict) -> list[dict]:
    flagged = []
    for f in metrics["files"]:
        hist = f["fun_length_histogram"]
        over = hist.get("51-100", 0) + hist.get("101+", 0)
        if over > 0:
            flagged.append({
                "rule": "functions-over-50-file-level",
                "file": f["path"],
                "detail": f"51-100:{hist.get('51-100', 0)}, 101+:{hist.get('101+', 0)}",
            })
    flagged.sort(key=lambda item: item["file"])
    return flagged


def _hotspot_top_n(metrics: dict, field: str, rule: str, top_n: int) -> list[dict]:
    candidates = [f for f in metrics["files"] if f[field] > 0]
    candidates.sort(key=lambda f: (-f[field], f["path"]))
    return [
        {"rule": rule, "file": f["path"], "detail": f"{field}={f[field]}"}
        for f in candidates[:top_n]
    ]


def _duplication_items(duplication: dict) -> list[dict]:
    items = []
    for cluster in duplication["clusters"]:
        files = sorted({occ["file"] for occ in cluster["occurrences"]})
        items.append({
            "rule": "duplication-cluster",
            "file": files[0] if files else "(unknown)",
            "detail": f"tokens={cluster['tokens']}, files={', '.join(files)}",
        })
    items.sort(key=lambda item: (item["file"], item["detail"]))
    return items


def _dep_violation_items(deps: dict) -> list[dict]:
    items = [
        {
            "rule": f"dep-violation:{v['rule']}",
            "file": v["file"],
            "detail": f"line {v['line']}: {v['import']} ({v['from_node']} -> {v['to_node']})",
        }
        for v in deps["violations"]
    ]
    items.sort(key=lambda item: (item["file"], item["detail"]))
    return items


def build_clean_pass(metrics: dict, duplication: dict, deps: dict) -> dict:
    flagged = (
        _files_over_loc(metrics, LOC_OVER_THRESHOLD)
        + _long_functions_by_file(metrics)
        + _hotspot_top_n(metrics, "var_count", "var-hotspot-top20", HOTSPOT_TOP_N)
        + _hotspot_top_n(metrics, "lateinit_count", "lateinit-hotspot-top20", HOTSPOT_TOP_N)
        + _duplication_items(duplication)
        + _dep_violation_items(deps)
    )
    flagged.sort(key=lambda item: (item["rule"], item["file"], item["detail"]))
    by_rule_count = {}
    for item in flagged:
        by_rule_count[item["rule"]] = by_rule_count.get(item["rule"], 0) + 1

    return {
        "flagged_items": flagged,
        "by_rule_count": dict(sorted(by_rule_count.items())),
        "totals": {"flagged_items": len(flagged)},
    }


def render_markdown(payload: dict) -> str:
    lines = ["# clean-pass", "", f"repo_sha: `{payload['repo_sha']}`", "",
              f"{payload['totals']['flagged_items']} rows flagged. No proposals: deciding what to do is the skill's job.",
              ""]

    lines += ["## By rule", "", "| rule | rows |", "|---|---|"]
    for rule, count in sorted(payload["by_rule_count"].items()):
        lines.append(f"| {rule} | {count} |")

    lines += ["", "## Flagged rows", "", "| rule | file | detail |", "|---|---|---|"]
    for item in payload["flagged_items"]:
        lines.append(f"| {item['rule']} | {item['file']} | {item['detail']} |")

    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    repo_sha = baseline.git_head_sha(repo_root)
    repo_dirty = baseline.is_repo_dirty(repo_root)
    versions = toolenv.tool_versions(TOOLS_ROOT)

    out_dir = TOOLS_ROOT / "out" / repo_sha
    metrics = baseline.load_json(out_dir / "metrics.json")
    duplication = baseline.load_json(out_dir / "duplication.json")
    deps = baseline.load_json(out_dir / "deps.json")

    content = build_clean_pass(metrics, duplication, deps)
    payload = baseline.base_envelope(TOOLS_ROOT, repo_sha, versions, repo_dirty)
    payload.update(content)

    baseline.write_json(out_dir / "clean-pass.json", payload)
    (out_dir / "clean-pass.md").write_text(render_markdown(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
