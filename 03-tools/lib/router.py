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

Fable 5.1 (owner decision L11, superseding L6's automatic proposals) enters
only on demand: the router never proposes it by itself. The owner requests
it with the task field `owner_named: true` (the one request field); the rule
`escalate-fable` then keeps the normal roster of the matched row (`base_rule`
in the result and the log) and appends one extra entry, role FABLE_ROLE, in
its own final step, always with requires_approval: true. It runs only when
the list `approvals` holds the exact string `escalate-fable`; otherwise it is
skipped and nothing replaces it (the team already runs). It may run alone when
the base roster is empty (exempt tier). Its effort is capped at
FABLE_EFFORT_CAP (and the catalog entry's effort_ceiling); a level above the
cap after clamping fails closed. The entry carries the catalog's positive
max_context_tokens, which also caps its cost estimate. L13: the step never
stops the team: offline and the budget drop it first, and a catalog without
the Fable model skips it with a reason. Hard limits the catalog cannot
override: at most MAX_PARALLEL roles per step; a model that is Fable or not
`admitted` never runs without that approval (a trial-slot `candidate` is the
one owner-enabled exception); no automatic `max` effort; Fable never above
`high`.

Input first goes through one validation step: a malformed catalog is
`guard:catalog`, a malformed task field `guard:input`, a date that is not a
real calendar day `guard:as_of`; each returns status error, an empty roster
and a reason naming the field, never an exception. `new_comments` is a
non-negative int (a bool is rejected); `modules` is a non-negative int count
or a list of module-name strings.

Offline (decision L4, R9): when the task has no `offline` key, main()
reads `offline` from the active project config (METODO_PROJECT_CONFIG, else
<tools>/config/project.json), else METODO_OFFLINE=1; the task wins over the
config, the config over the env (resolve_offline). route() never does.

Usage:
    lib/router.py <task.json> [--as-of YYYY-MM-DD] [--log [PATH]] [--config PATH]

Exit 0 status ok; 1 any other status (error, blocked, over_budget, owner);
2 usage, unreadable or malformed input (JSON that is not an object, any
USAGE_RULES result), or a log path inside the target repo.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
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
# The model the approval gate protects (L6, L11), whatever the catalog says.
FABLE_MODEL = "claude-fable-5-1"
# L11/L13: the kit role of the extra Fable step, its hard effort cap, and the
# optional label that lets offline and the budget drop it first.
FABLE_ROLE = "generic-deep-reasoner"
FABLE_EFFORT_CAP = "high"
FABLE_OPTIONAL = "fable-step"
# Every rule id route() can emit, in table order; the evaluator measures its
# fixture coverage against this one constant so the two cannot drift.
RULE_IDS = ("guard:input", "guard:catalog", "guard:as_of", "guard:task_kind", "guard:tier", "guard:lane",
            "guard:full_required", "P1", FABLE_RULE, "P2", "P3", "P4", "P5", "P6",
            "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B8", "B7", "error")
# Fail-closed fallthrough that no input passing the guards reaches since B8
# (tests/test_router.py proves it over the kind x tier grid).
UNREACHABLE_RULES = ("B7",)
# Malformed input, not a routing decision: the CLI exits 2, the MCP tool isError.
USAGE_RULES = ("guard:input", "guard:catalog", "guard:as_of")
# The highest effort any automatic step may set, whatever the catalog says.
AUTO_EFFORT_CAP = "xhigh"
DEFAULT_LOG = TOOLS_ROOT / "out" / "runs" / "routing.jsonl"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Provider level names on one scale, so a requested level can be clamped
# onto a model's own ladder (Gemini has no xhigh, local models only on/off).
EFFORT_RANK = {"off": 0, "none": 0, "minimal": 1, "low": 2, "on": 3, "medium": 3, "high": 4, "xhigh": 5, "max": 6}
LEVEL_AT_RANK = {0: "none", 1: "minimal", 2: "low", 3: "medium", 4: "high", 5: "xhigh", 6: "max"}

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
    FABLE_ROLE: "orchestrator",
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
    "fable": {"model": "claude-fable-5-1", "tier": "orchestrator", "effort": "high"},
}


class _Fail(Exception):
    """A rule that cannot be resolved fails closed with status error."""


# ---------------------------------------------------------------- helpers

def dumps(obj) -> str:
    """Deterministic JSON, same contract as baseline.write_json."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _normalized(task):
    if not isinstance(task, dict):
        return task
    task = dict(task)
    for key in ("approvals", "modules"):
        if _strings(task.get(key)):
            task[key] = sorted(set(task[key])) if key == "approvals" else sorted(task[key])
    return task


def inputs_hash(task) -> str:
    text = json.dumps(_normalized(task), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=repr)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------- validation

def _count(value) -> bool:
    """A non-negative int; a bool is not a count."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _amount(value) -> bool:
    """A finite non-negative number; a bool is not an amount."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _real_date(value) -> bool:
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def catalog_problem(catalog) -> str | None:
    """Why the catalog cannot be routed on, or None. Checks every shape the
    router reads, so a malformed catalog never reaches the table."""
    if not isinstance(catalog, dict):
        return f"catalog must be a JSON object, got {type(catalog).__name__}"
    if not isinstance(catalog.get("router", {}), dict):
        return "catalog router must be an object"
    tiers = catalog.get("tiers")
    if not isinstance(tiers, dict) or not tiers:
        return "catalog tiers must be a non-empty object"
    cfg = _cfg(catalog)
    cap = cfg.get("max_parallel")
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        return f"catalog router.max_parallel must be an int >= 1, got {cap!r}"
    ladder = cfg.get("tier_ladder")
    if not _strings(ladder) or len(ladder) < 2:
        return "catalog router.tier_ladder must list at least two tier names"
    ceiling = cfg.get("effort_ceiling")
    if not isinstance(ceiling, dict) or not isinstance(ceiling.get("tier"), str) \
            or ceiling.get("effort") not in EFFORT_RANK:
        return "catalog router.effort_ceiling must be {tier, effort} with a known effort"
    for key in ("never_automatic_effort", "optional_drop_order"):
        if not _strings(cfg.get(key)):
            return f"catalog router.{key} must be a list of strings"
    if not _amount(cfg.get("map_stale_days")):
        return "catalog router.map_stale_days must be a non-negative number"
    if not isinstance(cfg.get("trial_slot"), bool):
        return "catalog router.trial_slot must be a boolean"
    tokens = cfg.get("default_tokens")
    if not isinstance(tokens, dict) or not all(_count(tokens.get(k)) for k in ("assumed_tokens_in", "assumed_tokens_out")):
        return "catalog router.default_tokens needs non-negative int assumed_tokens_in/out"
    fable = cfg.get("fable")
    # L13: a missing model or tier only skips the Fable step; a present one must be well formed.
    if not isinstance(fable, dict) or not all(isinstance(fable.get(k, ""), str) for k in ("model", "tier", "effort")):
        return "catalog router.fable must be {model, tier, effort} strings"
    if fable.get("effort", FABLE_EFFORT_CAP) not in EFFORT_RANK:
        return "catalog router.fable.effort must be a known effort level"
    for tier in ladder:
        if tier not in tiers:
            return f"catalog tier {tier!r} is missing"
    for tier, body in tiers.items():
        problem = _tier_problem(tier, body)
        if problem:
            return problem
    for tier, body in tiers.items():
        for i, entry in enumerate(body["candidates"]):
            where = f"catalog tiers.{tier}.candidates[{i}].max_context_tokens"
            if entry["id"] == FABLE_MODEL and not _positive(entry.get("max_context_tokens")):
                # L13: the Fable entry's bounded context is mandatory, never 0 or absent.
                return f"{where} must be a positive int (Fable entry)"
            if tier == fable.get("tier") and entry["id"] == fable.get("model") \
                    and _context_cap(catalog, tier, entry["id"]) is None:
                return f"{where} (or the tier's) must bound the Fable slot's context"
    return None


def _positive(value) -> bool:
    return _count(value) and value > 0


def _tier_problem(tier: str, body) -> str | None:
    if not isinstance(body, dict):
        return f"catalog tier {tier!r} must be an object"
    if not isinstance(body.get("candidates"), list):
        return f"catalog tiers.{tier}.candidates must be a list"
    if body.get("max_context_tokens") is not None and not _positive(body["max_context_tokens"]):
        return f"catalog tiers.{tier}.max_context_tokens must be a positive int"
    assumptions = body.get("token_assumptions", {})
    if not isinstance(assumptions, dict) or not all(
            isinstance(t, dict) and _count(t.get("assumed_tokens_in")) and _count(t.get("assumed_tokens_out"))
            for t in assumptions.values()):
        return f"catalog tiers.{tier}.token_assumptions need non-negative int assumed_tokens_in/out"
    for i, entry in enumerate(body["candidates"]):
        where = f"catalog tiers.{tier}.candidates[{i}]"
        if not isinstance(entry, dict):
            return f"{where} must be an object"
        for key in ("provider", "id"):
            if not isinstance(entry.get(key), str) or not entry[key]:
                return f"{where}.{key} must be a non-empty string"
        if not _amount(entry.get("usd_in")):
            return f"{where}.usd_in must be a non-negative number"
        if "usd_out" in entry and not _amount(entry["usd_out"]):
            return f"{where}.usd_out must be a non-negative number"
        if not isinstance(entry.get("status", ""), str):
            return f"{where}.status must be a string"
        levels = entry.get("effort_levels", ["medium"])
        if not _strings(levels) or not levels:
            return f"{where}.effort_levels must be a non-empty list of strings"
        unknown = [lvl for lvl in levels if lvl not in EFFORT_RANK]
        if unknown:
            # L13: an unknown name has no rank, so no cap could hold against it.
            return f"{where}.effort_levels has unknown effort levels {unknown}"
        by_role = entry.get("effort_by_role", {})
        if not isinstance(by_role, dict) or not all(v in EFFORT_RANK for v in by_role.values()):
            return f"{where}.effort_by_role must map roles to known effort levels"
        if entry.get("effort_default", "medium") not in EFFORT_RANK:
            return f"{where}.effort_default must be a known effort level"
        if "effort_ceiling" in entry and entry["effort_ceiling"] not in EFFORT_RANK:
            return f"{where}.effort_ceiling must be a known effort level"
        if entry.get("max_context_tokens") is not None and not _positive(entry["max_context_tokens"]):
            return f"{where}.max_context_tokens must be a positive int"
        rows = entry.get("price_schedule", [])
        if not isinstance(rows, list) or not all(
                isinstance(r, dict) and _amount(r.get("usd_in")) and _amount(r.get("usd_out"))
                and (r.get("from") is None or isinstance(r.get("from"), str)) for r in rows):
            return f"{where}.price_schedule rows need numeric usd_in/usd_out and a string or null from"
    return None


_BOOL_FIELDS = ("critical_hit", "owner_gate", "full_required", "offline", "owner_named")
_PRIOR_COUNTS = ("stalls", "escalated_count", "findings", "schema_fail")
_PRIOR_STRINGS = ("role", "tier", "effort", "verifier", "judge_tier")


def input_problem(task, catalog: dict) -> str | None:
    """Why the task cannot be routed, naming the field, or None. None (or an
    absent key) means unset for every optional field."""
    if not isinstance(task, dict):
        return f"task must be a JSON object, got {type(task).__name__}"
    approvals = task.get("approvals")
    if approvals is not None and not _strings(approvals):
        return "approvals must be a list of strings"
    for key in _BOOL_FIELDS:
        if task.get(key) is not None and not isinstance(task[key], bool):
            return f"{key} must be a boolean"
    for key in ("budget_usd", "map_age_days"):
        if task.get(key) is not None and not _amount(task[key]):
            return f"{key} must be a non-negative number"
    for key in ("changed_lines", "new_comments"):
        if task.get(key) is not None and not _count(task[key]):
            return f"{key} must be a non-negative int"
    modules = task.get("modules")
    if modules is not None and not _count(modules) and not _strings(modules):
        return "modules must be a non-negative int or a list of strings"
    prior = task.get("prior")
    if prior is None:
        return None
    if not isinstance(prior, dict):
        return "prior must be an object"
    for key in _PRIOR_COUNTS:
        if prior.get(key) is not None and not _count(prior[key]):
            return f"prior.{key} must be a non-negative int"
    for key in _PRIOR_STRINGS:
        if prior.get(key) is not None and not isinstance(prior[key], str):
            return f"prior.{key} must be a string"
    truncated = prior.get("truncated")
    if truncated is not None and not isinstance(truncated, bool) and not _count(truncated):
        return "prior.truncated must be a boolean or a non-negative int"
    if prior.get("disagreement") is not None and not isinstance(prior["disagreement"], bool):
        return "prior.disagreement must be a boolean"
    p0 = prior.get("p0_from_lower_tier")
    if p0 is not None and p0 is not False and (not isinstance(p0, str) or p0 not in catalog["tiers"]):
        return "prior.p0_from_lower_tier must be a catalog tier name or false"
    return None


def load_project_config(tools_root: Path = TOOLS_ROOT, env=None) -> dict:
    """The active project config: METODO_PROJECT_CONFIG, else
    <tools_root>/config/project.json (the hooks' rule); unreadable = {}."""
    env = os.environ if env is None else env
    path = Path(env.get("METODO_PROJECT_CONFIG") or Path(tools_root) / "config" / "project.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_offline(task: dict, config: dict | None, env) -> dict:
    """A copy of task with the effective `offline`: the task's own key, else
    the config's, else METODO_OFFLINE=1. Absent everywhere = untouched."""
    if "offline" in task:
        return dict(task)
    if isinstance(config, dict) and "offline" in config:
        return dict(task, offline=bool(config["offline"]))
    if (env or {}).get("METODO_OFFLINE") == "1":
        return dict(task, offline=True)
    return dict(task)


def fallback_model(catalog: dict, role: str) -> str | None:
    """The model a role's frontmatter pins: the first admitted, non-local
    Anthropic entry of the role's default tier (ROLE_TIER), i.e. what the
    router launches when nothing raises the tier. None if there is none."""
    tier = ROLE_TIER.get(role)
    for entry in _candidates(catalog, tier) if tier else []:
        if _default_ok(entry) and entry.get("provider") == "anthropic" and not entry.get("local"):
            return entry.get("id")
    return None


def _default_ok(entry: dict) -> bool:
    """May a default row pick this entry: admitted and never Fable."""
    return entry.get("status") == "admitted" and entry.get("id") != FABLE_MODEL


def _gated(entry: dict, trial: bool) -> bool:
    """Needs owner approval to run: Fable, or any status but admitted (a
    trial-slot `candidate` excepted: the owner enables that slot)."""
    if entry.get("id") == FABLE_MODEL:
        return True
    if trial and entry.get("status") == "candidate":
        return False
    return entry.get("status") != "admitted"


def parallel_cap(catalog: dict) -> int:
    """The catalog's max_parallel, never above MAX_PARALLEL nor below 1."""
    return max(1, min(int(_cfg(catalog)["max_parallel"]), MAX_PARALLEL))


def _auto_effort(catalog: dict, effort: str) -> str:
    """An effort an automatic step may keep: at most the catalog ceiling and
    never above AUTO_EFFORT_CAP (so never `max`)."""
    ceiling = _cfg(catalog)["effort_ceiling"]["effort"]
    cap = min(EFFORT_RANK.get(ceiling, EFFORT_RANK[AUTO_EFFORT_CAP]), EFFORT_RANK[AUTO_EFFORT_CAP])
    if EFFORT_RANK.get(effort, EFFORT_RANK["medium"]) <= cap:
        return effort
    return LEVEL_AT_RANK[cap]


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
        elif _default_ok(entry) and bool(entry.get("local")) == local:
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


def _context_cap(catalog: dict, tier: str, model: str | None = None) -> int | None:
    """The tightest max_context_tokens of the model's own entry and its tier."""
    tier_cfg = (catalog.get("tiers") or {}).get(tier) or {}
    caps = [tier_cfg.get("max_context_tokens")]
    if model is not None:
        caps.append((_resolve(catalog, tier, model) or {}).get("max_context_tokens"))
    # L13: only None means absent; a 0 cap is a cap, never a missing one.
    caps = [int(c) for c in caps if c is not None]
    return min(caps) if caps else None


def _tokens(catalog: dict, tier: str, role: str, model: str | None = None) -> tuple[int, int]:
    tier_cfg = (catalog.get("tiers") or {}).get(tier) or {}
    tokens = (tier_cfg.get("token_assumptions") or {}).get(role) or _cfg(catalog)["default_tokens"]
    tokens_in = int(tokens["assumed_tokens_in"])
    cap = _context_cap(catalog, tier, model)
    if cap is not None:
        tokens_in = min(tokens_in, cap)
    return tokens_in, int(tokens["assumed_tokens_out"])


def _cost(catalog: dict, roster: list[dict], as_of: str) -> float:
    total = 0.0
    for e in roster:
        if e["launch"] != "run":
            continue
        entry = _resolve(catalog, e["tier"], e["model"])
        usd_in, usd_out = price_at(entry, as_of)
        tokens_in, tokens_out = _tokens(catalog, e["tier"], e["role"], e["model"])
        total += (tokens_in * usd_in + tokens_out * usd_out) / 1_000_000
    return round(total, 6)


def _fable_effort(entry: dict, effort: str) -> str:
    """L11: Fable never above FABLE_EFFORT_CAP, nor above its catalog
    effort_ceiling when that is lower. L13: the clamp onto the model's own
    ladder can land above the cap (a ladder with no level at or below it),
    so the result is checked after clamping and fails closed."""
    cap = EFFORT_RANK[FABLE_EFFORT_CAP]
    cap = min(cap, EFFORT_RANK.get(entry.get("effort_ceiling") or FABLE_EFFORT_CAP, cap))
    level = effort
    if level not in EFFORT_RANK or EFFORT_RANK[level] > cap:
        level = _clamp(entry, LEVEL_AT_RANK[cap])
    if level not in EFFORT_RANK or EFFORT_RANK[level] > cap:
        raise _Fail(f"{entry.get('id')} effort {level!r} is above the Fable cap {LEVEL_AT_RANK[cap]!r} "
                    "(its effort_levels have no level at or below it): fail closed")
    return level


def _entry(catalog: dict, role: str, tier: str, effort: str | None, *, step: int, order: str = "sequential",
           model: str | None = None, optional: str | None = None, trial: bool = False,
           requires_approval: bool = False, launch: str = "run", approved: bool = False,
           fable: bool = False, entry: dict | None = None) -> dict:
    entry = entry or _resolve(catalog, tier, model)
    if entry is None:
        raise _Fail(f"no admitted model in tier {tier} for {role}")
    if _gated(entry, trial):
        # Hard limit (L6): no catalog setting launches Fable or a non-admitted
        # model; only an exact owner approval passed in by escalate-fable does.
        requires_approval = True
        if not approved:
            launch = "skip"
    level = _clamp(entry, effort) if effort else role_effort(entry, role)
    # L13 verifier blocker: the deep-reasoner role keeps the Fable effort cap and
    # bounded context on any model, so P2/P3/P4 escalations of it stay at or below it.
    fable = fable or entry["id"] == FABLE_MODEL or role == FABLE_ROLE
    if fable:
        level = _fable_effort(entry, level)
    result = {
        "role": role,
        "tier": tier,
        "provider": entry["provider"],
        "model": entry["id"],
        "effort": level,
        "launch": launch,
        "order": order,
        "step": step,
        "requires_approval": requires_approval,
        "optional": optional,
        "trial": trial,
    }
    if fable:
        # L11: a bounded context budget the harness passes to the brief.
        result["max_context_tokens"] = _context_cap(catalog, tier, entry["id"])
    return result


def _modules(task: dict) -> int:
    modules = task.get("modules")
    count = len(modules) if isinstance(modules, list) else int(modules or 1)
    return max(count, 1)


def _batched(catalog: dict, role: str, tier: str, effort: str | None, count: int, first_step: int) -> list[dict]:
    cap = parallel_cap(catalog)
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
                      if EFFORT_RANK.get(lvl, 3) > rank and lvl not in cfg["never_automatic_effort"]
                      and EFFORT_RANK.get(lvl, 3) <= EFFORT_RANK[AUTO_EFFORT_CAP]]
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

def _join_fable(task: dict, catalog: dict, roster: list[dict], base_rule: str, reasons: list[str]) -> list[dict]:
    """L11: the owner-requested Fable step joins the team, never replaces it:
    the base roster stays as is and one FABLE_ROLE entry is appended in its
    own final step (step 1 when the base roster is empty). No substitute when
    it is not approved. L13: a catalog without the slot's model skips the step
    with a reason; the team is untouched (catalog_problem() already demanded a
    bounded context for the slot)."""
    fable = _cfg(catalog)["fable"]
    model, tier = fable.get("model"), fable.get("tier")
    entry = _resolve(catalog, tier, model) if model and tier else None
    if entry is None:
        reasons.append(f"{FABLE_RULE}: owner requested Fable (owner_named) but the catalog has no "
                       f"{model or 'model'} in tier {tier or '?'}; step skipped, the {base_rule} roster stands")
        return roster
    # Exact list membership: input_problem() already rejected any non-list.
    approved = FABLE_RULE in list(task.get("approvals") or [])
    step = max((e["step"] for e in roster), default=0) + 1
    extra = _entry(catalog, FABLE_ROLE, tier, fable.get("effort") or FABLE_EFFORT_CAP, step=step, entry=entry,
                   optional=FABLE_OPTIONAL, requires_approval=True, launch="run" if approved else "skip",
                   approved=approved, fable=True)
    reasons.append(f"{FABLE_RULE}: owner requested {entry['id']} (owner_named); it joins the {base_rule} "
                   f"roster as {FABLE_ROLE} in step {step} at {extra['effort']}, "
                   f"context <= {extra['max_context_tokens']} tokens")
    if extra["launch"] != "run":
        reasons.append(f"fable requested, awaiting owner approval ({FABLE_RULE} not in approvals); "
                       f"the {base_rule} team runs without it")
    return roster + [extra]


def _drop_fable(roster: list[dict], why: str, reasons: list[str]) -> None:
    """L13: the optional Fable step goes first, before any team role."""
    for e in roster:
        if e["optional"] == FABLE_OPTIONAL and e["launch"] == "run":
            e["launch"] = "skip"
            reasons.append(f"{why}: dropped the owner-requested {FABLE_ROLE} step first ({e['model']})")


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
    if tier == "high" and int(prior.get("escalated_count") or 0) >= 2:
        # L11: no automatic Fable; two escalations exhaust the ladder.
        reasons.append("high-tier receipt escalated twice: the ladder is exhausted, the owner decides")
        return "P1", [], "owner"
    truncated = prior.get("truncated")
    if truncated:
        if truncated is not True and int(truncated) >= 2:
            reasons.append("truncated again after the split: the owner decides")
            return "P2", [], "owner"
        role = _prior_role(prior, "P2")
        slot_tier, effort = _prior_slot(catalog, prior, role)
        effort = _auto_effort(catalog, effort)
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
        ladder = cfg["tier_ladder"]
        if p0 not in ladder[:-1]:
            # L13: a P0 from the top of the ladder (or above it) has no higher
            # automatic tier to confirm it; it is never dropped silently.
            reasons.append(f"P0 from the {p0} tier: no higher automatic tier can confirm it; the owner decides")
            return "P4", [], "owner"
        if task.get("critical_hit"):
            # L13: on a critical path the P0 is confirmed on the large tier at the
            # highest automatic effort, whatever tier it came from; never on Fable.
            top, effort = ladder[-1], _auto_effort(catalog, "xhigh")
            reasons.append(f"P0 from the {p0} tier on a critical path: confirmed on the {top} tier at {effort}")
            return "P4", [_entry(catalog, role, top, effort, step=1)], "ok"
        up = ladder[ladder.index(p0) + 1]
        reasons.append(f"P0 from the {p0} tier is confirmed one tier up ({up}) before it counts")
        return "P4", [_entry(catalog, role, up, None, step=1)], "ok"
    if prior.get("disagreement"):
        effort = "xhigh" if task.get("critical_hit") else "high"
        if prior.get("judge_tier") == "large":
            # L11: after the large judge, raise its effort once; at the ceiling the owner decides.
            ceiling = EFFORT_RANK[_auto_effort(catalog, "xhigh")]
            before = prior.get("effort") or effort
            if EFFORT_RANK.get(before, EFFORT_RANK["medium"]) >= ceiling:
                reasons.append(f"adversaries still disagree after the large judge at {before}: the owner decides")
                return "P5", [], "owner"
            effort = LEVEL_AT_RANK[ceiling]
            reasons.append(f"adversaries still disagree after the large judge at {before}: large judge at {effort}")
            return "P5", [_entry(catalog, "generic-judge", "large", effort, step=1)], "ok"
        reasons.append(f"adversaries disagree: large judge at {effort}")
        return "P5", [_entry(catalog, "generic-judge", "large", effort, step=1)], "ok"
    if str(prior.get("verifier") or "").upper() == "FAIL":
        role = "generic-proposer"
        slot_tier = prior.get("tier") or "medium"
        effort = _auto_effort(catalog, prior.get("effort") or ("high" if tier == "high" else "medium"))
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
        reasons.append(f"map: one cartographer per module ({count}), {map_tier}/medium, parallel in batches of {parallel_cap(catalog)}")
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
    _drop_fable(roster, "offline", reasons)
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
    _drop_fable(roster, "budget", reasons)
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
    rule, base, roster, status = None, None, [], "ok"
    # One validation step, before any rule reads a field (fail closed): the
    # task's shape, the catalog, the date, then every task field.
    if not isinstance(task, dict):
        rule, problem = "guard:input", input_problem(task, {})
    elif (problem := catalog_problem(catalog)) is not None:
        rule = "guard:catalog"
    elif not _real_date(as_of):
        rule, problem = "guard:as_of", f"as_of must be a real YYYY-MM-DD date, got {as_of!r}"
    elif (problem := input_problem(task, catalog)) is not None:
        rule = "guard:input"
    if problem:
        reasons.append(problem)
        return _result(task, catalog, as_of, rule, [], "error", reasons, rule)
    prior = task.get("prior") or {}
    if task.get("task_kind") not in TASK_KINDS:
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
            if status == "ok" and task.get("owner_named"):
                base, rule = rule, FABLE_RULE
                roster = _join_fable(task, catalog, roster, base, reasons)
        except _Fail as exc:
            roster, status = [], "error"
            rule = rule or "error"
            reasons.append(str(exc))
        if status == "ok" and task.get("offline"):
            status = _offline(catalog, roster, reasons)
        if status == "ok" and task.get("budget_usd") is not None:
            status = _budget(catalog, roster, float(task["budget_usd"]), as_of, reasons)
        # L13: "runs" is said only once the post-passes kept the Fable step.
        for e in roster:
            if status == "ok" and e["optional"] == FABLE_OPTIONAL and e["launch"] == "run":
                reasons.append(f"owner approved {FABLE_RULE}: {e['model']} runs")
    return _result(task, catalog, as_of, rule, roster, status, reasons, base or rule)


def _result(task, catalog, as_of, rule, roster, status, reasons, base_rule=None) -> dict:
    cost = _cost(catalog, roster, as_of) if roster and rule and not rule.startswith("guard:") else 0.0
    # Only the approvals that granted a launch are recorded (L6, L11): today
    # the one gated launch is the Fable step of escalate-fable, run with approval.
    granted = [FABLE_RULE] if rule == FABLE_RULE and any(
        e["launch"] == "run" and e["requires_approval"] for e in roster) else []
    return {
        "approvals": granted,
        "as_of": as_of,
        # L13: the table row that ran before the Fable step (equals `rule` without one).
        "base_rule": base_rule or rule,
        "catalog_version": catalog.get("version") if isinstance(catalog, dict) else None,
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
    line["base_rule"] = result.get("base_rule") or result["rule"]
    line["roster"] = summary
    # L6: an owner approval (e.g. escalate-fable) is recorded in the log itself.
    line["approvals"] = list(result.get("approvals") or [])
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
        print("route: cannot read input: " + " ".join(str(exc).split()), file=sys.stderr)
        return 2
    if not isinstance(task, dict):
        print(f"route: the task must be a JSON object, got {type(task).__name__}", file=sys.stderr)
        return 2
    task = resolve_offline(task, load_project_config(TOOLS_ROOT, os.environ), os.environ)
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
    if result["rule"] in USAGE_RULES:
        # Malformed input is a usage error, not a routing decision: no log line.
        print(f"route: {result['rule']}: " + "; ".join(result["reasons"]), file=sys.stderr)
        return 2
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(log_line(result) + "\n")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
