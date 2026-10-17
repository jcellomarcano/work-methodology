#!/usr/bin/env python3
"""Deterministic evaluator of the router (odd/tasks/model-router.md R8b).

Runs router.route() on every fixture in tests/fixtures/router/*.json
against the catalog (config/model-tiers.json) and scores each decision
(routing-method.md §4):

- rule_ok, status_ok: the rule id and status match `expect`.
- roster_ok: exact multiset of (role, model, effort, launch).
- roles_missing / roles_extra: role names expected to run that do not, and
  roles that run without being expected (under- and over-provisioning).
- effort_or_tier_above / below: for a role in both rosters with another
  model or effort, whether the actual one sits above or below the expected
  one; tier first (catalog tier_ladder, then the other catalog tiers in
  order), then effort (the model's own ladder in the catalog, else the
  router's common scale).
- cost (the router's estimate at `as_of`) and cost_ok against the optional
  `expect.cost_max_usd`.
- max_parallel_step and fanout_ok: no step runs more roles than the owner's
  cap (router.MAX_PARALLEL, decision L4), whatever the catalog says.

Totals: passed, failed, total, total_cost_usd. Coverage: rule_coverage is
the set of router.RULE_IDS fired by the fixtures; rules_uncovered is the
reachable rest (router.UNREACHABLE_RULES are listed apart). The report is
deterministic JSON (sorted keys, no timestamps), byte-identical per input.

Fixture: {"name", "as_of", "input": <task>, "expect": {"rule", "status",
"roster": [{"role", "model", "effort", "launch"}], "cost_max_usd"?}}.

Usage:
    lib/router_eval.py [--fixtures DIR] [--out FILE]

The report goes to FILE (or stdout); one summary line goes to stderr.
Exit 0 every fixture passed; 1 any fixture failed; 2 unreadable input.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline, router  # noqa: E402

DEFAULT_FIXTURES = TOOLS_ROOT / "tests" / "fixtures" / "router"
DEFAULT_CONFIG = TOOLS_ROOT / "config" / "model-tiers.json"
KEYS = ("role", "model", "effort", "launch")


def load_fixtures(folder) -> list[dict]:
    return [baseline.load_json(path) for path in sorted(Path(folder).glob("*.json"))]


def _tier_order(catalog: dict) -> list[str]:
    ladder = list(router._cfg(catalog)["tier_ladder"])
    return ladder + [t for t in (catalog.get("tiers") or {}) if t not in ladder]


def _model_rank(catalog: dict, model: str) -> int:
    """Lowest tier that lists the model; unknown models rank -1."""
    order = _tier_order(catalog)
    ranks = [order.index(t) for t in order
             if any(e.get("id") == model for e in router._candidates(catalog, t))]
    return min(ranks) if ranks else -1


def _effort_cmp(catalog: dict, model: str, actual: str, expected: str) -> int:
    for tier in _tier_order(catalog):
        entry = router._resolve(catalog, tier, model)
        levels = (entry or {}).get("effort_levels") or []
        if actual in levels and expected in levels:
            return (levels.index(actual) > levels.index(expected)) - (levels.index(actual) < levels.index(expected))
    a, e = router.EFFORT_RANK.get(actual, 3), router.EFFORT_RANK.get(expected, 3)
    return (a > e) - (a < e)


def _tuples(roster: list[dict]) -> Counter:
    return Counter(tuple(e[k] for k in KEYS) for e in roster)


def _running_roles(roster: list[dict]) -> Counter:
    return Counter(e["role"] for e in roster if e["launch"] == "run")


def _rank_key(catalog: dict, e: dict):
    return (_model_rank(catalog, e["model"]), router.EFFORT_RANK.get(e["effort"], 3), e["model"], e["effort"])


def _drift(catalog: dict, actual: list[dict], expected: list[dict]) -> tuple[list[dict], list[dict]]:
    """Pair running entries of the same role (both sorted by rank) and report
    each pair whose model or effort differs, as above or below."""
    above, below = [], []
    for role in sorted(set(_running_roles(actual)) & set(_running_roles(expected))):
        acts = sorted((e for e in actual if e["role"] == role and e["launch"] == "run"), key=lambda e: _rank_key(catalog, e))
        exps = sorted((e for e in expected if e["role"] == role and e["launch"] == "run"), key=lambda e: _rank_key(catalog, e))
        for act, exp in zip(acts, exps):
            if (act["model"], act["effort"]) == (exp["model"], exp["effort"]):
                continue
            tier = _model_rank(catalog, act["model"]) - _model_rank(catalog, exp["model"])
            if tier:
                by, sign = "tier", (tier > 0) - (tier < 0)
            else:
                by, sign = "effort", _effort_cmp(catalog, act["model"], act["effort"], exp["effort"])
            if sign == 0:
                continue  # same tier and effort on another model: roster_ok carries it
            item = {"role": role, "by": by, "actual": f"{act['model']}/{act['effort']}",
                    "expected": f"{exp['model']}/{exp['effort']}"}
            (above if sign > 0 else below).append(item)
    return above, below


def evaluate_fixture(fixture: dict, catalog: dict) -> dict:
    expect = fixture["expect"]
    result = router.route(fixture["input"], catalog, fixture["as_of"])
    actual = [{k: e[k] for k in KEYS} for e in result["roster"]]
    expected = [{k: e[k] for k in KEYS} for e in expect.get("roster") or []]
    act_t, exp_t = _tuples(actual), _tuples(expected)
    act_r, exp_r = _running_roles(actual), _running_roles(expected)
    above, below = _drift(catalog, actual, expected)
    per_step = Counter(e["step"] for e in result["roster"] if e["launch"] == "run")
    max_step = max(per_step.values(), default=0)
    cost = result["cost_estimate_usd"]
    cost_max = expect.get("cost_max_usd")
    row = {
        "name": fixture["name"],
        "rule": result["rule"],
        "status": result["status"],
        "rule_ok": result["rule"] == expect["rule"],
        "status_ok": result["status"] == expect["status"],
        "roster_ok": act_t == exp_t,
        "roles_missing": sorted((exp_r - act_r).elements()),
        "roles_extra": sorted((act_r - exp_r).elements()),
        "entries_missing": [dict(zip(KEYS, t)) for t in sorted((exp_t - act_t).elements())],
        "entries_extra": [dict(zip(KEYS, t)) for t in sorted((act_t - exp_t).elements())],
        "effort_or_tier_above": above,
        "effort_or_tier_below": below,
        "cost": cost,
        "cost_max_usd": cost_max,
        "cost_ok": cost_max is None or cost <= float(cost_max),
        "max_parallel_step": max_step,
        "fanout_ok": max_step <= router.MAX_PARALLEL,
    }
    row["passed"] = all(row[k] for k in ("rule_ok", "status_ok", "roster_ok", "cost_ok", "fanout_ok"))
    return row


def evaluate(fixtures_dir=DEFAULT_FIXTURES, catalog: dict | None = None) -> dict:
    catalog = catalog if catalog is not None else baseline.load_json(DEFAULT_CONFIG)
    rows = sorted((evaluate_fixture(fx, catalog) for fx in load_fixtures(fixtures_dir)), key=lambda r: r["name"])
    fired = {r["rule"] for r in rows} & set(router.RULE_IDS)
    reachable = set(router.RULE_IDS) - set(router.UNREACHABLE_RULES)
    passed = sum(1 for r in rows if r["passed"])
    return {
        "catalog_version": catalog.get("version"),
        "fixtures": rows,
        "rule_coverage": sorted(fired),
        "rules_uncovered": sorted(reachable - fired),
        "rules_unreachable": sorted(router.UNREACHABLE_RULES),
        "totals": {
            "failed": len(rows) - passed,
            "passed": passed,
            "total": len(rows),
            "total_cost_usd": round(sum(r["cost"] for r in rows), 6),
        },
    }


def render(report: dict) -> str:
    return router.dumps(report)


def summary(report: dict) -> str:
    t = report["totals"]
    reachable = len(report["rule_coverage"]) + len(report["rules_uncovered"])
    line = (f"router_eval: {t['total']} fixtures, {t['passed']} passed, {t['failed']} failed; "
            f"rules {len(report['rule_coverage'])}/{reachable} covered")
    if report["rules_uncovered"]:
        line += " (uncovered: " + ", ".join(report["rules_uncovered"]) + ")"
    line += f"; unreachable: {', '.join(report['rules_unreachable']) or 'none'}; total_cost_usd {t['total_cost_usd']}"
    failing = [r["name"] for r in report["fixtures"] if not r["passed"]]
    if failing:
        line += "; failing: " + ", ".join(failing)
    return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixtures", default=str(DEFAULT_FIXTURES), help="folder of fixture JSON files")
    parser.add_argument("--out", default=None, help="write the JSON report here instead of stdout")
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.fixtures)
    except (OSError, ValueError, KeyError) as exc:
        print(f"router_eval: cannot read input: {exc}", file=sys.stderr)
        return 2
    text = render(report)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    print(summary(report), file=sys.stderr)
    return 0 if report["totals"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
