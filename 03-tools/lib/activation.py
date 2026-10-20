#!/usr/bin/env python3
"""Activation policy (odd/research/context/activation.md section 3, WU14):
which kit elements are ON for a task, from facts no LLM computes.

profile(inputs) picks a profile with the first-match rows below and records
every reason; element_mode(profile, element, modifiers) reads the mode of one
element (OFF | LOG | WARN | BLOCK) from the matrix in config/activation.json,
then applies the modifiers. Both are pure and deterministic. The only I/O is
load_config() and the session floor (session_profile / session_floor), which
keeps the highest profile seen in out/hooks/<session>/profile.json: the tier
only rises within a session.

Rows (first match):
    P0 rdd_on false                                   -> bare
    P1 tier high, or critical, or task_kind release   -> full
    P2 tier medium                                    -> standard
    P3 tier low                                       -> scripts
    P4 tier exempt (M4: phase explore counts here)    -> light
    P5 tier not computable (None / unknown)           -> standard
P0 is the owner's kill switch, not a tier: the session floor never lifts it.

The absolute set is BLOCK in every profile whatever the modifiers, and the
loader refuses a config that drops one of its elements or lowers its mode.

Usage:
    lib/activation.py --tier T [--task-kind K] [--runtime claude|pi] [--caller main|subagent]
                      [--offline] [--phase explore|edit|deliver] [--critical] [--rdd-off]
                      [--session S] [--config F]
Output: {profile, rule, reasons, tier, elements}. Exit 2 on a usage or config error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = TOOLS_ROOT / "config" / "activation.json"
SESSION_FILE = "profile.json"

PROFILES = ("bare", "light", "scripts", "standard", "full")
RANK = {name: i for i, name in enumerate(PROFILES)}
MODES = ("OFF", "LOG", "WARN", "BLOCK")
TIERS = ("exempt", "low", "medium", "high")
TIER_RANK = {name: i for i, name in enumerate(TIERS)}
UNKNOWN_TIERS = (None, "unknown")
# activation.md section 3 kinds plus the router's task kinds.
TASK_KINDS = ("research", "docs", "code", "review", "release", "verify", "map", "implement", "comment")
RUNTIMES = ("claude", "claude-code", "pi")
CALLERS = ("main", "subagent")
PHASES = ("explore", "edit", "deliver")

ELEMENTS = ("push_gate", "history_rewrite", "subagent_scope", "subagent_output", "touched_paths",
            "session_start_status", "reply_lint", "human_reply_skill", "roles", "comment_gate", "docs_caps",
            "test_sectors", "kit_status_drift", "router")
ABSOLUTE = ("subagent_build_files", "force_push", "subagent_delivery", "budget_deny", "main_build_file_ask")
MAIN_ONLY = ("push_gate", "session_start_status", "reply_lint", "human_reply_skill")
MODIFIER_KEYS = ("caller", "runtime", "offline", "gradle", "kit_repo", "verdicts")
VERDICTS = {"demote": "OFF", "promote": "BLOCK"}
THRESHOLDS = ("min_days", "min_fires", "precision_min", "override_max", "act_rate_min", "max_false_positives",
              "main_deny_max_false_positives", "max_windows")
CONFIG_KEYS = ("_comment", "version", "absolute", "matrix", "notes", "roles_cap", "thresholds")


class ActivationConfigError(ValueError):
    """The activation config is unreadable or invalid; nothing is guessed."""


# ------------------------------------------------------------------ profile

def _check(name: str, value, allowed) -> None:
    if value is not None and value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(str(a) for a in allowed)}; got {value!r}")


def profile(inputs: dict, floor: str | None = None) -> dict:
    """Pure: {profile, rule, reasons, tier}. `floor` is the session's highest
    profile so far; the result is never below it (except P0)."""
    tier = inputs.get("tier")
    if tier not in UNKNOWN_TIERS:
        _check("tier", tier, TIERS)
    _check("task_kind", inputs.get("task_kind"), TASK_KINDS)
    _check("runtime", inputs.get("runtime"), RUNTIMES)
    _check("caller", inputs.get("caller"), CALLERS)
    _check("phase", inputs.get("phase"), PHASES)
    _check("floor", floor, PROFILES)
    reasons: list[str] = []
    critical, kind = bool(inputs.get("critical")), inputs.get("task_kind")

    if not inputs.get("rdd_on", True):
        return {"profile": "bare", "rule": "P0", "reasons": ["rdd.enabled is false: bare (absolute set only)"],
                "tier": tier if tier not in UNKNOWN_TIERS else None}
    if tier == "high" or critical or kind == "release":
        why = [w for w, hit in (("tier high", tier == "high"), ("critical path", critical),
                                ("task_kind release", kind == "release")) if hit]
        rule, name = "P1", "full"
        reasons.append(", ".join(why) + ": full")
    else:
        if inputs.get("phase") == "explore" and tier not in UNKNOWN_TIERS and tier != "exempt":
            reasons.append(f"M4 phase explore: nothing touched yet, tier {tier} counts as exempt")
            tier = "exempt"
        if tier == "medium":
            rule, name = "P2", "standard"
        elif tier == "low":
            rule, name = "P3", "scripts"
        elif tier == "exempt":
            rule, name = "P4", "light"
        else:
            rule, name = "P5", "standard"
        reasons.append(f"tier {tier if tier not in UNKNOWN_TIERS else 'not computable'}: {name}"
                       + (" (safe default)" if rule == "P5" else ""))
    if floor is not None and RANK[floor] > RANK[name]:
        reasons.append(f"session floor: {floor} (tier only rises within a session)")
        name = floor
    return {"profile": name, "rule": rule, "reasons": reasons, "tier": tier if tier not in UNKNOWN_TIERS else None}


# ------------------------------------------------------------------ config

def validate_config(data) -> dict:
    """Returns the config when valid; raises ActivationConfigError naming the problem."""
    if not isinstance(data, dict):
        raise ActivationConfigError("activation config must be a JSON object")
    extra = sorted(set(data) - set(CONFIG_KEYS))
    if extra:
        raise ActivationConfigError(f"unknown key(s): {', '.join(extra)}")
    known = set(ELEMENTS) | set(ABSOLUTE)
    absolute = data.get("absolute")
    if not isinstance(absolute, list) or any(e not in known for e in absolute):
        raise ActivationConfigError("absolute must list known elements")
    dropped = [e for e in ABSOLUTE if e not in absolute]
    if dropped:
        raise ActivationConfigError(f"config lowers the absolute set: {', '.join(dropped)} dropped (owner-only)")
    matrix = data.get("matrix")
    if not isinstance(matrix, dict):
        raise ActivationConfigError("matrix must be an object")
    unknown = sorted(set(matrix) - known)
    if unknown:
        raise ActivationConfigError(f"unknown element(s) in matrix: {', '.join(unknown)}")
    for element in ELEMENTS + ABSOLUTE:
        row = matrix.get(element)
        if not isinstance(row, dict):
            raise ActivationConfigError(f"missing element in matrix: {element}")
        bad = sorted(set(row) - set(PROFILES))
        if bad:
            raise ActivationConfigError(f"unknown profile(s) for {element}: {', '.join(bad)}")
        for name in PROFILES:
            if name not in row:
                raise ActivationConfigError(f"missing profile {name} for {element}")
            if row[name] not in MODES:
                raise ActivationConfigError(f"unknown mode {row[name]!r} for {element} in {name}")
            if element in absolute and row[name] != "BLOCK":
                raise ActivationConfigError(f"config lowers the absolute set: {element} is {row[name]} in {name}")
    caps = data.get("roles_cap", {})
    if not isinstance(caps, dict) or set(caps) - set(PROFILES) or any(
            not isinstance(v, list) or not all(isinstance(r, str) for r in v) for v in caps.values()):
        raise ActivationConfigError("roles_cap must map profiles to lists of role names")
    thresholds = data.get("thresholds")
    if not isinstance(thresholds, dict) or any(
            isinstance(thresholds.get(k), bool) or not isinstance(thresholds.get(k), (int, float)) for k in THRESHOLDS):
        raise ActivationConfigError("thresholds must hold a number for each of: " + ", ".join(THRESHOLDS))
    return data


def load_config(path: Path | str | None = None) -> dict:
    path = Path(path) if path else DEFAULT_CONFIG
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActivationConfigError(f"cannot read {path}: {exc}") from exc
    return validate_config(data)


_DEFAULT: dict | None = None


def _default_config() -> dict:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = load_config(DEFAULT_CONFIG)
    return _DEFAULT


# ------------------------------------------------------------------ matrix

def element_mode(profile_name: str, element: str, modifiers: dict | None = None, config: dict | None = None) -> str:
    """OFF | LOG | WARN | BLOCK for one element. Modifiers (activation.md
    section 3), applied after the profile: M6 verdicts (demote OFF, promote
    BLOCK), M2 runtime pi (subagent output BLOCK -> LOG), M5 gradle false
    (test sectors OFF), kit_repo false (kit-status drift OFF), M1 caller
    subagent (main-only elements OFF). M3 offline changes no matrix element
    (the router's offline post-pass owns it); M4 lives in profile()."""
    _check("profile", profile_name, PROFILES)
    if element not in ELEMENTS and element not in ABSOLUTE:
        raise ValueError(f"unknown element {element!r}")
    modifiers = modifiers or {}
    extra = sorted(set(modifiers) - set(MODIFIER_KEYS))
    if extra:
        raise ValueError(f"unknown modifier(s): {', '.join(extra)}")
    _check("caller", modifiers.get("caller"), CALLERS)
    _check("runtime", modifiers.get("runtime"), RUNTIMES)
    verdicts = modifiers.get("verdicts") or {}
    for name, verdict in verdicts.items():
        _check(f"verdict for {name}", verdict, tuple(VERDICTS))
    if element in ABSOLUTE:
        return "BLOCK"
    mode = (config or _default_config())["matrix"][element][profile_name]
    if element in verdicts:
        mode = VERDICTS[verdicts[element]]
    if modifiers.get("runtime") == "pi" and element == "subagent_output" and mode == "BLOCK":
        mode = "LOG"
    if modifiers.get("gradle") is False and element == "test_sectors":
        mode = "OFF"
    if modifiers.get("kit_repo") is False and element == "kit_status_drift":
        mode = "OFF"
    if modifiers.get("caller") == "subagent" and element in MAIN_ONLY:
        mode = "OFF"
    return mode


def elements(profile_name: str, modifiers: dict | None = None, config: dict | None = None) -> dict:
    return {e: element_mode(profile_name, e, modifiers, config) for e in ELEMENTS + ABSOLUTE}


def roles_cap(profile_name: str, config: dict | None = None) -> list[str]:
    _check("profile", profile_name, PROFILES)
    return list(((config or _default_config()).get("roles_cap") or {}).get(profile_name) or [])


# ------------------------------------------------------------- session floor

def session_floor(session_dir: Path | str) -> str | None:
    """The highest profile stored for the session, or None (absent or unreadable)."""
    try:
        stored = json.loads((Path(session_dir) / SESSION_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    name = stored.get("profile") if isinstance(stored, dict) else None
    return name if name in PROFILES else None


def session_profile(inputs: dict, session_dir: Path | str) -> dict:
    """profile() with the session floor, then stores the highest profile and tier seen."""
    sdir = Path(session_dir)
    floor = session_floor(sdir)
    result = profile(inputs, floor=floor)
    if result["rule"] == "P0":
        return result
    try:
        stored = json.loads((sdir / SESSION_FILE).read_text(encoding="utf-8"))
        stored = stored if isinstance(stored, dict) else {}
    except (OSError, json.JSONDecodeError):
        stored = {}
    tiers = [t for t in (stored.get("tier"), result["tier"]) if t in TIERS]
    record = {"profile": result["profile"], "rule": result["rule"],
              "tier": max(tiers, key=TIER_RANK.__getitem__) if tiers else None}
    if record != {k: stored.get(k) for k in record}:
        try:
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / SESSION_FILE).write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            pass
    return result


# --------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Activation profile and element modes (JSON).")
    parser.add_argument("--tier", required=True, choices=TIERS + ("unknown",))
    parser.add_argument("--task-kind", choices=TASK_KINDS)
    parser.add_argument("--runtime", choices=RUNTIMES)
    parser.add_argument("--caller", choices=CALLERS)
    parser.add_argument("--phase", choices=PHASES)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--critical", action="store_true")
    parser.add_argument("--rdd-off", action="store_true")
    parser.add_argument("--session")
    parser.add_argument("--config")
    args = parser.parse_args(argv)
    inputs = {"rdd_on": not args.rdd_off, "tier": None if args.tier == "unknown" else args.tier,
              "critical": args.critical, "task_kind": args.task_kind, "runtime": args.runtime,
              "caller": args.caller, "phase": args.phase, "offline": args.offline}
    try:
        config = load_config(args.config)
        if args.session:
            hooks = Path(os.environ.get("METODO_HOOKS_DIR") or TOOLS_ROOT / "out" / "hooks")
            result = session_profile(inputs, hooks / args.session)
        else:
            result = profile(inputs)
        modifiers = {k: v for k, v in (("caller", args.caller), ("runtime", args.runtime)) if v}
        if args.offline:
            modifiers["offline"] = True
        result["elements"] = elements(result["profile"], modifiers, config)
    except ValueError as exc:  # ActivationConfigError included
        print(f"activation: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
