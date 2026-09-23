#!/usr/bin/env python3
"""Runs output_lint.py over a bench's outputs (`<model>-<arm>-<kind>.md`) and aggregates.

Writes `results.json` (sorted keys, with the pass's `tool_sha` and `config_sha`) and
`summary.json` with what the minutes need: PASS per arm and per model, median word
count, FAIL and WARN per rule, technical layer presence, code-fence lines, and the
rules that get worse in the `con` arm. The model never re-derives any of these
numbers: it copies them from here.

Usage:
    lib/bench_output_lint.py <outputs-dir> [--lang es] [--audience public] [--config ...] [--personal ...]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import output_lint  # noqa: E402


def run(out_dir: Path, config: dict, lang: str, audience: str, personal: list[str]) -> tuple[list[dict], dict]:
    rows = []
    for path in sorted(out_dir.glob("*.md")):
        model, arm, kind = path.stem.split("-", 2)
        text = path.read_text(encoding="utf-8")
        result = output_lint.check(text, config, kind=kind, lang=lang, audience=audience, personal_terms=personal)
        rows.append({
            "arm": arm,
            "code_fence_lines": result["layers"]["code_fence_lines"],
            "fails": sorted(r["id"] for r in result["rules"] if r["status"] == "FAIL"),
            "file": path.name,
            "human_lines": result["layers"]["human_lines"],
            "kind": kind,
            "model": model,
            "technical_heading": result["layers"]["technical_heading"],
            "total_lines": sum(1 for l in text.splitlines() if l.strip()),
            "verdict": result["verdict"],
            "warns": sorted(r["id"] for r in result["rules"] if r["status"] == "WARN"),
            "words": len(text.split()),
        })
    return rows, summarize(rows)


def _count(rows: list[dict], key: str) -> dict:
    counts: dict = {}
    for row in rows:
        for rule_id in row[key]:
            counts[rule_id] = counts.get(rule_id, 0) + 1
    return dict(sorted(counts.items()))


def summarize(rows: list[dict]) -> dict:
    arms = sorted({r["arm"] for r in rows})
    models = sorted({r["model"] for r in rows})
    by_arm = {}
    for arm in arms:
        sub = [r for r in rows if r["arm"] == arm]
        by_arm[arm] = {
            "code_fence_lines": sum(r["code_fence_lines"] for r in sub),
            "fail_by_rule": _count(sub, "fails"),
            "fail_total": sum(len(r["fails"]) for r in sub),
            "median_words": statistics.median(r["words"] for r in sub) if sub else 0,
            "n": len(sub),
            "pass": sum(1 for r in sub if r["verdict"] == "PASS"),
            "technical_heading": sum(1 for r in sub if r["technical_heading"]),
            "warn_by_rule": _count(sub, "warns"),
        }
    by_model = {}
    for model in models:
        by_model[model] = {}
        for arm in arms:
            sub = [r for r in rows if r["arm"] == arm and r["model"] == model]
            by_model[model][arm] = {
                "fail_total": sum(len(r["fails"]) for r in sub),
                "median_words": statistics.median(r["words"] for r in sub) if sub else 0,
                "n": len(sub),
                "pass": sum(1 for r in sub if r["verdict"] == "PASS"),
            }
    worse = {}
    if "sin" in by_arm and "con" in by_arm:
        for rule_id, n in by_arm["con"]["fail_by_rule"].items():
            before = by_arm["sin"]["fail_by_rule"].get(rule_id, 0)
            if n > before:
                worse[rule_id] = {"con": n, "sin": before}
    return {"by_arm": by_arm, "by_model": by_model, "worse_in_con": worse}


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent.parent / "config"
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out_dir")
    parser.add_argument("--lang", default="es")
    parser.add_argument("--audience", default="public")
    parser.add_argument("--config", default=str(here / "output-lint.json"))
    parser.add_argument("--personal", default=str(here / "output-lint.personal.json"))
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    rows, summary = run(out_dir, config, args.lang, args.audience, output_lint.load_personal(Path(args.personal)))
    shas = {"config_sha": output_lint._sha(config_path), "tool_sha": output_lint._sha(Path(output_lint.__file__).resolve())}
    (out_dir.parent / "results.json").write_text(json.dumps({"rows": rows, **shas}, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir.parent / "summary.json").write_text(json.dumps({**summary, **shas}, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({**summary, **shas}, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
