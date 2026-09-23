#!/usr/bin/env python3
"""Derives a candidate's review tier (exempt / low / medium / high) and its
lenses, from facts rather than prose: touched paths against
shared_build_files, money_paths, exempt_globs and tests_globs; the lane
returned by change_card_validator; the diff size. The table is fixed and
the first row that applies wins; every match is recorded in `reasons`.

derive() is pure (no git) and is what the tests exercise; gather() does
the git and change-card reads for real use.

Usage:
    lib/rdd_risk.py --inputs <inputs.json> [--config <project.json>]
    lib/rdd_risk.py --repo <repo> --base <ref> [--change-card <card>] [--config <project.json>]

Output: {tier, reasons, lenses, lens_focus, owner_gate, consent, inputs}.
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
from lib import change_card_validator as ccv  # noqa: E402
from lib import role_contract_validator as rcv  # noqa: E402

TIERS = ("exempt", "low", "medium", "high")
LENS_ORDER = ("flujo-critico", "jamas-peor-que-antes", "tests-anti-flake", "simplicidad")
DEFAULT_RDD = {
    "exempt_globs": ["**/*.md", "docs/**"],
    "tests_globs": ["**/src/test/**", "**/src/androidTest/**"],
    "low_max_changed_lines": 120,
    "lens_paths": {},
}


def glob_match(path: str, pattern: str) -> bool:
    """fnmatch, plus a case fnmatch does not cover: '**/X' must also match
    an X at the repo root (README.md against '**/*.md')."""
    if fnmatch.fnmatch(path, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:])


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(glob_match(path, p) for p in patterns)


def rdd_config(config: dict) -> dict:
    merged = dict(DEFAULT_RDD)
    merged.update(config.get("rdd") or {})
    return merged


def _lens_focus(touched: list[str], lens_paths: dict) -> str:
    for lens in LENS_ORDER[:-1]:
        if any(matches_any(path, lens_paths.get(lens, [])) for path in touched):
            return lens
    return LENS_ORDER[-1]


def derive(inputs: dict, config: dict) -> dict:
    rdd = rdd_config(config)
    touched = sorted(inputs.get("touched_paths") or [])
    routing = inputs.get("routing")
    what_it_risks = inputs.get("what_it_risks")
    changed_lines = int(inputs.get("added") or 0) + int(inputs.get("removed") or 0)
    has_card = bool(inputs.get("has_change_card"))
    shared_build = [p for p in rcv.always_forbidden_patterns(config) if ".claude" not in p]
    money_paths = list(config.get("money_paths") or [])
    reasons: list[str] = []
    owner_gate = False

    def hits(patterns: list[str]) -> list[str]:
        return [p for p in touched if matches_any(p, patterns)]

    if not touched:
        tier = "exempt"
        reasons.append("no touched paths")
    elif hits(shared_build):
        tier = "high"
        owner_gate = True
        reasons.append("touches shared_build_files: " + ", ".join(hits(shared_build)))
    elif any(p.startswith(prefix) for p in touched for prefix in money_paths):
        tier = "high"
        reasons.append("touches money_paths: " + ", ".join(p for p in touched if any(p.startswith(m) for m in money_paths)))
    elif routing == "opus":
        tier = "high"
        reasons.append("change card routing is opus")
    elif len(hits(rdd["exempt_globs"])) == len(touched):
        tier = "exempt"
        reasons.append("all paths match exempt_globs")
    elif len(hits(rdd["exempt_globs"] + rdd["tests_globs"])) == len(touched):
        tier = "low"
        reasons.append("all paths are tests or exempt")
    elif not has_card:
        tier = "medium"
        reasons.append("no change card: medium is the floor and start will demand one")
    elif what_it_risks == "none" and changed_lines <= int(rdd["low_max_changed_lines"]):
        tier = "low"
        reasons.append(f"what_it_risks is 'none' and {changed_lines} changed lines <= {rdd['low_max_changed_lines']}")
    else:
        tier = "medium"
        reasons.append("default: no critical path, not trivial")

    if tier == "high":
        lenses, focus = list(LENS_ORDER), None
    elif tier == "medium":
        focus = _lens_focus(touched, rdd.get("lens_paths") or {})
        lenses = [focus]
    else:
        lenses, focus = [], None

    return {
        "tier": tier,
        "reasons": reasons,
        "lenses": lenses,
        "lens_focus": focus,
        "owner_gate": owner_gate,
        "consent": "pending" if tier == "high" else "n/a",
        "inputs": {
            "touched_paths": touched,
            "routing": routing,
            "what_it_risks": what_it_risks,
            "added": int(inputs.get("added") or 0),
            "removed": int(inputs.get("removed") or 0),
            "has_change_card": has_card,
        },
    }


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def diff_facts(repo: Path, base: str) -> dict:
    """Files and changed lines between merge-base(base, HEAD) and HEAD
    (three dots: what the branch contributes, not what the base advanced)."""
    names = sorted(p for p in _git(repo, "diff", "--name-only", f"{base}...HEAD").splitlines() if p.strip())
    added = removed = 0
    for line in _git(repo, "diff", "--numstat", f"{base}...HEAD").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            added += int(parts[0])
            removed += int(parts[1])
    return {"touched_paths": names, "added": added, "removed": removed}


def card_facts(card_path: Path | None, config: dict) -> dict:
    if card_path is None:
        return {"has_change_card": False, "routing": None, "what_it_risks": None, "card_verdict": None}
    text = Path(card_path).read_text(encoding="utf-8")
    ccv.configure_properties(config)
    result = ccv.validate(text, ccv.invariant_prefix_from_config(config), ccv.extra_invariant_tokens_from_config(config))
    fields, _ = ccv.parse_fields(text)
    what_it_risks = ccv._routing_category(ccv._field_text(fields.get("What it risks", ""))) if "What it risks" in fields else None
    return {"has_change_card": True, "routing": result["routing"], "what_it_risks": what_it_risks, "card_verdict": result["verdict"]}


def gather(repo: Path, base: str, card_path: Path | None, config: dict) -> dict:
    inputs = diff_facts(repo, base)
    inputs.update(card_facts(card_path, config))
    return inputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", default=None, help="JSON with touched_paths/added/removed/routing/what_it_risks/has_change_card")
    parser.add_argument("--repo", default=None)
    parser.add_argument("--base", default=None)
    parser.add_argument("--change-card", default=None)
    parser.add_argument("--config", default=None, help="config/project.json")
    args = parser.parse_args(argv)

    config_path = Path(args.config) if args.config else TOOLS_ROOT / "config" / "project.json"
    config = baseline.load_json(config_path) if config_path.exists() else {}

    if args.inputs:
        inputs = baseline.load_json(args.inputs)
    elif args.repo and args.base:
        inputs = gather(Path(args.repo).resolve(), args.base, Path(args.change_card) if args.change_card else None, config)
    else:
        parser.error("pass --inputs, or --repo and --base")

    print(json.dumps(derive(inputs, config), sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
