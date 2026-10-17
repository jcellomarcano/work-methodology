#!/usr/bin/env python3
"""Deterministic multi-agent router (odd/tasks/model-router.md R8).

From a task descriptor it returns the roster to launch: role, model tier,
provider, model, effort, run or skip, parallel or sequential, step. The
rules are the first-match table of odd/research/model-router/routing-method.md
§3 plus B8 (task_kind verify, decision L7): guards, then the P-rows (react to the previous step), then the B-rows
(base case), then two post-passes (offline, budget). The catalog is
config/model-tiers.json; prices come from each entry's price_schedule at
`as_of`, which is an input: route() never reads the clock, the filesystem
or the environment, so the same input gives byte-identical output.

Fable 5.1 (owner decision L6) is never in a default roster. Only the rule
`escalate-fable` proposes it, always with requires_approval: true; it
launches only when `escalate-fable` is in `approvals`, otherwise Opus 5.5
at xhigh runs instead.

Usage:
    lib/router.py <task.json> [--as-of YYYY-MM-DD] [--log [PATH]] [--config PATH]

Exit 0 status ok; 1 any other status (error, blocked, over_budget, owner);
2 usage, unreadable input, or a log path inside the target repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline  # noqa: E402

TASK_KINDS = ("map", "implement", "review", "docs", "comment", "verify")
RDD_TIERS = ("exempt", "low", "medium", "high")
MAX_PARALLEL = 3
FABLE_RULE = "escalate-fable"
# Every rule id route() can emit, in table order; the evaluator measures its
# fixture coverage against this one constant so the two cannot drift.
RULE_IDS = ("guard:as_of", "guard:task_kind", "guard:tier", "guard:lane", "guard:full_required",
            "P1", FABLE_RULE, "P2", "P3", "P4", "P5", "P6",
            "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B8", "B7", "error")
# Fail-closed fallthrough that no input passing the guards reaches since B8
# (tests/test_router.py proves it over the kind x tier grid).
UNREACHABLE_RULES = ("B7",)
DEFAULT_LOG = TOOLS_ROOT / "out" / "runs" / "routing.jsonl"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Provider level names on one scale, so a requested level can be clamped
# onto a model's own ladder (Gemini has no xhigh, local models only on/off).
EFFORT_RANK = {"off": 0, "none": 0, "minimal": 1, "low": 2, "on": 3, "medium": 3, "high": 4, "xhigh": 5, "max": 6}

# Default model tier of each kit role when the previous step does not say.
ROLE_TIER = {
    "generic-style-reviewer": "small",
    "generic-comment-gate": "small",
    "generic-human-reviewer": "small",
    "generic-mechanic": "small",
    "generic-cartographer": "medium",
    "generic-verifier": "medium",
    "generic-boundary-reviewer": "medium",
    "generic-judge": "medium",
    "generic-proposer": "medium",
    "generic-challenger": "large",
    "generic-blind-spot-adversary": "large",
}

ROUTER_DEFAULTS = {
    "max_parallel": MAX_PARALLEL,
    "trial_slot": False,
    "optional_drop_order": ["trial-adversary", "judge-zero-findings", "stale-map-cartographer"],
    "map_stale_days": 7,
    "effort_ceiling": {"tier": "large", "effort": "xhigh"},
    "never_automatic_effort": ["max"],
    "tier_ladder": ["small", "medium", "large"],
    "default_tokens": {"assumed_tokens_in": 30000, "assumed_tokens_out": 4000},
    "fable": {"model": "claude-fable-5-1", "tier": "orchestrator", "effort": "high",
              "fallback": {"model": "claude-opus-5-5", "tier": "large", "effort": "xhigh"}},
}


class _Fail(Exception):
    """A rule that cannot be resolved fails closed with status error."""


# ---------------------------------------------------------------- helpers

def dumps(obj) -> str:
    """Deterministic JSON, same contract as baseline.write_json."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _normalized(task: dict) -> dict:
    task = dict(task)
    if isinstance(task.get("approvals"), list):
        task["approvals"] = sorted(set(task["approvals"]))
    if isinstance(task.get("modules"), list):
        task["modules"] = sorted(task["modules"])
    return task


def inputs_hash(task: dict) -> str:
    text = json.dumps(_normalized(task), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cfg(catalog: dict) -> dict:
    merged = dict(ROUTER_DEFAULTS)
    merged.update(catalog.get("router") or {})
    return merged


def _candidates(catalog: dict, tier: str) -> list[dict]:
    return ((catalog.get("tiers") or {}).get(tier) or {}).get("candidates") or []


def _resolve(catalog: dict, tier: str, model: str | None = None, local: bool = False) -> dict | None:
    """The named model in this tier, or the first admitted entry in catalog
    order (remote unless local=True)."""
    for entry in _candidates(catalog, tier):
        if model is not None:
            if entry.get("id") == model:
                return entry
        elif entry.get("status") == "admitted" and bool(entry.get("local")) == local:
            return entry
    return None


def _clamp(entry: dict, effort: str) -> str:
    """The model's own level at or below the requested one (its lowest if none)."""
    levels = entry.get("effort_levels") or [effort]
    if effort in levels:
        return effort
    rank = EFFORT_RANK.get(effort, EFFORT_RANK["medium"])
    below = [lvl for lvl in levels if EFFORT_RANK.get(lvl, 3) <= rank]
    if not below:
        return levels[0]
    return max(below, key=lambda lvl: EFFORT_RANK.get(lvl, 3))


def role_effort(entry: dict, role: str) -> str:
    return (entry.get("effort_by_role") or {}).get(role) or entry.get("effort_default") or "medium"


def price_at(entry: dict, as_of: str) -> tuple[float, float]:
    """Last schedule row whose `from` is on or before as_of; from=null is
    the row valid on the read date with an unknown start."""
    rows = sorted(entry.get("price_schedule") or [], key=lambda r: r.get("from") or "")
    if not rows:
        return float(entry.get("usd_in") or 0.0), float(entry.get("usd_out") or 0.0)
    chosen = rows[0]
    for row in rows:
        if row.get("from") is None or row["from"] <= as_of:
            chosen = row
    return float(chosen["usd_in"]), float(chosen["usd_out"])


def _tokens(catalog: dict, tier: str, role: str) -> tuple[int, int]:
    tier_cfg = (catalog.get("tiers") or {}).get(tier) or {}
    tokens = (tier_cfg.get("token_assumptions") or {}).get(role) or _cfg(catalog)["default_tokens"]
    tokens_in = int(tokens["assumed_tokens_in"])
    if tier_cfg.get("max_context_tokens"):
        tokens_in = min(tokens_in, int(tier_cfg["max_context_tokens"]))
    return tokens_in, int(tokens["assumed_tokens_out"])


def _cost(catalog: dict, roster: list[dict], as_of: str) -> float:
    total = 0.0
    for e in roster:
        if e["launch"] != "run":
            continue
        entry = _resolve(catalog, e["tier"], e["model"])
        usd_in, usd_out = price_at(entry, as_of)
        tokens_in, tokens_out = _tokens(catalog, e["tier"], e["role"])
        total += (tokens_in * usd_in + tokens_out * usd_out) / 1_000_000
    return round(total, 6)


def _entry(catalog: dict, role: str, tier: str, effort: str | None, *, step: int, order: str = "sequential",
           model: str | None = None, optional: str | None = None, trial: bool = False,
           requires_approval: bool = False, launch: str = "run") -> dict:
    entry = _resolve(catalog, tier, model)
    if entry is None:
        raise _Fail(f"no admitted model in tier {tier} for {role}")
    return {
        "role": role,
        "tier": tier,
        "provider": entry["provider"],
        "model": entry["id"],
        "effort": _clamp(entry, effort) if effort else role_effort(entry, role),
        "launch": launch,
        "order": order,
        "step": step,
        "requires_approval": requires_approval,
        "optional": optional,
        "trial": trial,
    }


def _modules(task: dict) -> int:
    modules = task.get("modules")
    count = len(modules) if isinstance(modules, list) else int(modules or 1)
    return max(count, 1)


def _batched(catalog: dict, role: str, tier: str, effort: str | None, count: int, first_step: int) -> list[dict]:
    cap = int(_cfg(catalog)["max_parallel"])
    return [_entry(catalog, role, tier, effort, step=first_step + i // cap, order="parallel") for i in range(count)]


def escalate(catalog: dict, role: str, tier: str, effort: str, failure: str) -> tuple[str, str] | None:
    """One step up the ladder (routing-method.md §3). failure='diligence'
    raises effort on the same model first; 'wrong' (or no higher automatic
    level) moves one tier up at the role's default effort. None = ceiling,
    the owner decides."""
    cfg = _cfg(catalog)
    ladder = list(cfg["tier_ladder"])
    ceiling = cfg["effort_ceiling"]
    if failure == "diligence":
        entry = _resolve(catalog, tier)
        if entry is not None:
            rank = EFFORT_RANK.get(effort, 3)
            higher = [lvl for lvl in entry.get("effort_levels") or []
                      if EFFORT_RANK.get(lvl, 3) > rank and lvl not in cfg["never_automatic_effort"]]
            if higher:
                nxt = min(higher, key=lambda lvl: EFFORT_RANK.get(lvl, 3))
                over = tier == ceiling["tier"] and EFFORT_RANK.get(nxt, 3) > EFFORT_RANK[ceiling["effort"]]
                if not over:
                    return tier, nxt
    if tier not in ladder or ladder.index(tier) + 1 >= len(ladder):
        return None
    up = ladder[ladder.index(tier) + 1]
    entry = _resolve(catalog, up)
    if entry is None:
        return None
    return up, role_effort(entry, role)


# ------------------------------------------------------------ the table

def _fable_reason(task: dict, prior: dict) -> str | None:
    if task.get("owner_named"):
        return "one-off owner-named task"
    if task.get("critical_hit") and prior.get("p0_from_lower_tier"):
        return "P0 on a critical path"
    if prior.get("disagreement") and prior.get("judge_tier") == "large":
        return "adversary disagreement unresolved after the large judge"
    if task.get("tier") == "high" and int(prior.get("escalated_count") or 0) >= 2:
        return "high-tier receipt escalated twice"
    return None


def _escalate_fable(task: dict, catalog: dict, reasons: list[str], why: str) -> list[dict]:
    fable = _cfg(catalog)["fable"]
    approved = FABLE_RULE in (task.get("approvals") or [])
    role = "owner-named-task" if task.get("owner_named") else "generic-judge"
    roster = [_entry(catalog, role, fable["tier"], fable["effort"], step=1, model=fable["model"],
                     requires_approval=True, launch="run" if approved else "skip")]
    reasons.append(f"{FABLE_RULE}: {why}")
    if approved:
        reasons.append(f"owner approved {FABLE_RULE}: {fable['model']} runs")
    else:
        fb = fable["fallback"]
        roster.append(_entry(catalog, role, fb["tier"], fb["effort"], step=1, model=fb["model"]))
        reasons.append(f"{fable['model']} awaits owner approval ({FABLE_RULE} not in approvals); "
                       f"{fb['model']} at {fb['effort']} runs instead")
    return roster


def _prior_role(prior: dict, rule: str, default: str | None = None) -> str:
    role = prior.get("role") or default
    if not role:
        raise _Fail(f"rule {rule} needs prior.role")
    return role


def _prior_slot(catalog: dict, prior: dict, role: str) -> tuple[str, str]:
    tier = prior.get("tier") or ROLE_TIER.get(role, "medium")
    if prior.get("effort"):
        return tier, prior["effort"]
    entry = _resolve(catalog, tier)
    if entry is None:
        raise _Fail(f"no admitted model in tier {tier} for {role}")
    return tier, role_effort(entry, role)


def _review_high(task: dict, catalog: dict, prior: dict, first_step: int, reasons: list[str]) -> list[dict]:
    """B6: two large adversaries in parallel (+ optional trial), verifier, judge."""
    critical = bool(task.get("critical_hit"))
    adversary = "xhigh" if critical else "high"
    roster = [
        _entry(catalog, "generic-challenger", "large", adversary, step=first_step, order="parallel"),
        _entry(catalog, "generic-blind-spot-adversary", "large", adversary, step=first_step, order="parallel"),
    ]
    if _cfg(catalog)["trial_slot"]:
        incumbent = roster[0]["provider"]
        for cand in _candidates(catalog, "large"):
            if cand.get("status") == "candidate" and cand["provider"] != incumbent and not cand.get("local"):
                roster.append(_entry(catalog, "generic-blind-spot-adversary", "large", None, step=first_step,
                                     order="parallel", model=cand["id"], optional="trial-adversary", trial=True))
                reasons.append(f"trial slot: {cand['id']} as a third adversary, rated by a blind judge")
                break
    roster.append(_entry(catalog, "generic-verifier", "medium", "high", step=first_step + 1))
    if critical:
        roster.append(_entry(catalog, "generic-judge", "large", "xhigh", step=first_step + 2))
    else:
        roster.append(_entry(catalog, "generic-judge", "medium", "high", step=first_step + 2))
    reasons.append("high tier: owner consent before launch" + (" (owner gate: shared build)" if task.get("owner_gate") else ""))
    return roster


def _rows(task: dict, prior: dict, catalog: dict, reasons: list[str]) -> tuple[str, list[dict], str]:
    kind, tier = task["task_kind"], task["tier"]
    cfg = _cfg(catalog)

    if int(prior.get("stalls") or 0) >= 2:
        reasons.append("two stalls on this step: the owner decides")
        return "P1", [], "owner"
    why = _fable_reason(task, prior)
    if why:
        return FABLE_RULE, _escalate_fable(task, catalog, reasons, why), "ok"
    truncated = prior.get("truncated")
    if truncated:
        if truncated is not True and int(truncated) >= 2:
            reasons.append("truncated again after the split: the owner decides")
            return "P2", [], "owner"
        role = _prior_role(prior, "P2")
        slot_tier, effort = _prior_slot(catalog, prior, role)
        reasons.append("previous output truncated: same role, tier and effort, split by module, once")
        return "P2", _batched(catalog, role, slot_tier, effort, _modules(task), 1), "ok"
    schema_fail = int(prior.get("schema_fail") or 0)
    if schema_fail:
        role = _prior_role(prior, "P3")
        slot_tier, effort = _prior_slot(catalog, prior, role)
        failure = "wrong" if schema_fail >= 2 else "diligence"
        step = escalate(catalog, role, slot_tier, effort, failure)
        if step is None:
            reasons.append("schema FAIL at the ladder ceiling (large/xhigh): the owner decides")
            return "P3", [], "owner"
        reasons.append(f"schema FAIL x{schema_fail}: {'tier' if failure == 'wrong' else 'effort'} +1")
        return "P3", [_entry(catalog, role, step[0], step[1], step=1)], "ok"
    p0 = prior.get("p0_from_lower_tier")
    if p0:
        role = _prior_role(prior, "P4", "generic-judge")
        from_tier = p0 if p0 in ("small", "medium") else prior.get("tier") or "medium"
        if from_tier in ("small", "medium"):
            ladder = cfg["tier_ladder"]
            up = ladder[ladder.index(from_tier) + 1]
            reasons.append(f"P0 from the {from_tier} tier is confirmed one tier up before it counts")
            return "P4", [_entry(catalog, role, up, None, step=1)], "ok"
    if prior.get("disagreement"):
        effort = "xhigh" if task.get("critical_hit") else "high"
        reasons.append(f"adversaries disagree: large judge at {effort}")
        return "P5", [_entry(catalog, "generic-judge", "large", effort, step=1)], "ok"
    if str(prior.get("verifier") or "").upper() == "FAIL":
        role = "generic-proposer"
        slot_tier = prior.get("tier") or "medium"
        effort = prior.get("effort") or ("high" if tier == "high" else "medium")
        reasons.append("verifier FAIL: proposer again at the same tier and effort, once; a second FAIL counts as a stall (P1)")
        return "P6", [_entry(catalog, role, slot_tier, effort, step=1)], "ok"

    if tier == "exempt":
        reasons.append("exempt tier: scripts only (docs_lint)")
        return "B0", [], "ok"
    if tier == "low" or kind == "comment":
        reasons.append("scripts only: contract, comment_gate.py")
        roster = []
        if int(task.get("new_comments") or 0) > 0:
            roster.append(_entry(catalog, "generic-comment-gate", "small", "low", step=1))
            reasons.append("new comments > 0: comment gate small/low")
        return "B1", roster, "ok"
    if kind == "map":
        count = _modules(task)
        map_tier = "small" if count == 1 else "medium"
        reasons.append(f"map: one cartographer per module ({count}), {map_tier}/medium, parallel in batches of {cfg['max_parallel']}")
        return "B2", _batched(catalog, "generic-cartographer", map_tier, "medium", count, 1), "ok"
    if kind == "implement" and tier in ("medium", "high"):
        roster: list[dict] = []
        step = 1
        age = task.get("map_age_days")
        if age is None or int(age) > int(cfg["map_stale_days"]):
            roster.append(_entry(catalog, "generic-cartographer", "medium", "medium", step=step,
                                 optional="stale-map-cartographer"))
            reasons.append("map missing or older than %s days: cartographer first" % cfg["map_stale_days"])
            step += 1
        roster.append(_entry(catalog, "generic-proposer", "medium", "high" if tier == "high" else "medium", step=step))
        roster.append(_entry(catalog, "generic-verifier", "medium", "high", step=step + 1))
        if tier == "medium":
            return "B3", roster, "ok"
        reasons.append("high tier: the high review (B6) runs on the diff after the verifier")
        return "B4", roster + _review_high(task, catalog, prior, step + 2, reasons), "ok"
    if kind in ("review", "docs") and tier == "medium":
        roster = [
            _entry(catalog, "generic-challenger", "medium", "high", step=1, order="parallel"),
            _entry(catalog, "generic-verifier", "medium", "medium", step=1, order="parallel"),
        ]
        if task.get("lens_focus"):
            reasons.append(f"challenger lens: {task['lens_focus']}")
        findings = prior.get("findings")
        if findings is None:
            roster.append(_entry(catalog, "generic-judge", "medium", "high", step=2, optional="judge-zero-findings"))
            reasons.append("judge runs only if findings > 0")
        elif int(findings) > 0:
            roster.append(_entry(catalog, "generic-judge", "medium", "high", step=2))
        else:
            roster.append(_entry(catalog, "generic-judge", "medium", "high", step=2,
                                 optional="judge-zero-findings", launch="skip"))
            reasons.append("zero findings: judge skipped")
        return "B5", roster, "ok"
    if kind in ("review", "docs") and tier == "high":
        return "B6", _review_high(task, catalog, prior, 1, reasons), "ok"
    if kind == "verify" and tier in ("medium", "high"):
        # L7: verification is routable; the large judge only when findings exist.
        roster = [_entry(catalog, "generic-verifier", "medium", "high", step=1)]
        reasons.append("verify: verifier medium/high")
        if tier == "high":
            effort = "xhigh" if task.get("critical_hit") else "high"
            if int(prior.get("findings") or 0) > 0:
                roster.append(_entry(catalog, "generic-judge", "large", effort, step=2))
                reasons.append(f"verify high with findings: large judge at {effort}")
            else:
                roster.append(_entry(catalog, "generic-judge", "large", effort, step=2,
                                     optional="judge-zero-findings", launch="skip"))
                reasons.append("verify high without prior findings: large judge skipped")
        return "B8", roster, "ok"
    reasons.append(f"no row for task_kind={kind} at tier={tier}: fail closed")
    return "B7", [], "error"


# ----------------------------------------------------------- post-passes

def _offline(catalog: dict, roster: list[dict], reasons: list[str]) -> str:
    blocked = []
    for e in roster:
        if e["launch"] != "run":
            continue
        local = _resolve(catalog, e["tier"], local=True)
        if local is not None:
            e.update(provider=local["provider"], model=local["id"], effort=_clamp(local, e["effort"]))
        elif e["optional"]:
            e["launch"] = "skip"
            reasons.append(f"offline: optional {e['role']} dropped (no admitted local model in {e['tier']})")
        else:
            blocked.append(f"{e['role']}@{e['tier']}")
    if blocked:
        for e in roster:
            e["launch"] = "skip"
        reasons.append("offline: no admitted local model for " + ", ".join(sorted(set(blocked))) + "; nothing launches remote")
        return "blocked"
    return "ok"


def _budget(catalog: dict, roster: list[dict], budget: float, as_of: str, reasons: list[str]) -> str:
    if _cost(catalog, roster, as_of) <= budget:
        return "ok"
    for kind in _cfg(catalog)["optional_drop_order"]:
        for e in roster:
            if e["optional"] == kind and e["launch"] == "run":
                e["launch"] = "skip"
                reasons.append(f"budget: dropped optional {kind} ({e['role']})")
        if _cost(catalog, roster, as_of) <= budget:
            return "ok"
    reasons.append(f"budget: mandatory roles cost more than {budget} USD; the owner decides")
    return "over_budget"


# ------------------------------------------------------------- route()

def route(task: dict, catalog: dict, as_of: str) -> dict:
    """Pure: no clock, no filesystem, no environment."""
    reasons: list[str] = []
    rule, roster, status = None, [], "ok"
    prior = task.get("prior") or {}
    if not isinstance(as_of, str) or not DATE_RE.match(as_of):
        rule, status = "guard:as_of", "error"
        reasons.append(f"as_of must be YYYY-MM-DD, got {as_of!r}")
    elif task.get("task_kind") not in TASK_KINDS:
        rule, status = "guard:task_kind", "error"
        reasons.append(f"unknown task_kind {task.get('task_kind')!r}")
    elif task.get("tier") not in RDD_TIERS:
        rule, status = "guard:tier", "error"
        reasons.append(f"tier missing or unknown: {task.get('tier')!r}")
    elif task.get("lane") == "opus" and task["tier"] != "high":
        rule, status = "guard:lane", "error"
        reasons.append("lane opus with a tier below high: stale input")
    elif task.get("full_required") and task["tier"] != "high":
        rule, status = "guard:full_required", "error"
        reasons.append("full_required bumps the layer to high: stale input")
    else:
        try:
            rule, roster, status = _rows(task, prior, catalog, reasons)
        except _Fail as exc:
            roster, status = [], "error"
            rule = rule or "error"
            reasons.append(str(exc))
        if status == "ok" and task.get("offline"):
            status = _offline(catalog, roster, reasons)
        if status == "ok" and task.get("budget_usd") is not None:
            status = _budget(catalog, roster, float(task["budget_usd"]), as_of, reasons)
    cost = _cost(catalog, roster, as_of) if roster and rule and not rule.startswith("guard:") else 0.0
    return {
        "as_of": as_of,
        "catalog_version": catalog.get("version"),
        "cost_estimate_usd": cost,
        "inputs_hash": inputs_hash(task),
        "reasons": reasons,
        "roster": roster,
        "rule": rule,
        "status": status,
    }


# ---------------------------------------------------------------- the CLI

def log_line(result: dict) -> str:
    summary = [{k: e[k] for k in ("role", "tier", "model", "effort", "launch", "step")} for e in result["roster"]]
    line = {k: result[k] for k in ("as_of", "catalog_version", "inputs_hash", "rule", "status")}
    line["roster"] = summary
    return json.dumps(line, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _worktree_root(repo: str) -> Path:
    try:
        out = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        if out:
            return Path(out).resolve()
    except (subprocess.SubprocessError, OSError):
        pass
    return Path(repo).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task", help="task descriptor JSON")
    parser.add_argument("--as-of", default=None, help="YYYY-MM-DD; prices are read at this date (default: task.as_of)")
    parser.add_argument("--log", nargs="?", const=str(DEFAULT_LOG), default=None,
                        help=f"append one JSON line per decision (default path {DEFAULT_LOG})")
    parser.add_argument("--config", default=str(TOOLS_ROOT / "config" / "model-tiers.json"))
    args = parser.parse_args(argv)

    try:
        task = baseline.load_json(args.task)
        catalog = baseline.load_json(args.config)
    except (OSError, ValueError) as exc:
        print(f"route: cannot read input: {exc}", file=sys.stderr)
        return 2
    if os.environ.get("METODO_OFFLINE") == "1":
        task = dict(task, offline=True)
    as_of = args.as_of or task.get("as_of")
    if not as_of:
        print("route: pass --as-of YYYY-MM-DD (the router never reads the clock)", file=sys.stderr)
        return 2

    log_path = None
    if args.log:
        log_path = Path(args.log).resolve()
        if task.get("repo"):
            root = _worktree_root(str(task["repo"]))
            if log_path == root or root in log_path.parents:
                print(f"route: refusing to log inside the target repo worktree ({root}); "
                      f"use the tools instance, e.g. {DEFAULT_LOG}", file=sys.stderr)
                return 2

    result = route(task, catalog, as_of)
    sys.stdout.write(dumps(result))
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(log_line(result) + "\n")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
