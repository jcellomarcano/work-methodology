#!/usr/bin/env python3
"""PreToolUse Task|Agent: the launch of another agent. Absolute (always,
even with RDD off): a kit role launches nothing outside its contract's
may_spawn; an agent with no kit contract is not a kit role and is left to
its runtime. Non-absolute (warn|block mode): the launch prompt is a goal
contract (lib/brief_check.py: one goal, a specific role, a bounded
context) and its ROLE is the role being launched. In warn mode the agent
reads one visible METODO-WARN line; off and log only write the ledger.

lib/brief_check.py is imported after the absolute deny, so a partial
instance copy without lib/ keeps that deny and fails open on the rest."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

HOOK = "guard_spawn"
TOOLS = ("Task", "Agent")
TEMPLATE = "04-templates/brief.md"
FIX = f" Write the brief from {TEMPLATE} and launch again (methodology.md paragraph 9)."


def roster(brief_check, repo: Path | None) -> list[str]:
    names: set[str] = set()
    for directory in ([repo / ".claude" / "agents"] if repo is not None else []) + [
            c.TOOLS_ROOT.parent / "01-roles" / "agents", c.TOOLS_ROOT / "claude" / "agents"]:
        if directory.is_dir():
            names.update(brief_check.roster_names(directory))
    return sorted(names)


def problems(result: dict, max_lines: int) -> list[str]:
    found = []
    for key in ("missing", "empty", "duplicate", "out_of_order"):
        if result[key]:
            found.append(f"{key.replace('_', ' ')}: {', '.join(result[key])}")
    if result["role_general_purpose"]:
        found.append("ROLE is general-purpose: name the one thing this agent does")
    if result["role_unknown"]:
        found.append("ROLE is outside the roster and declares no model=")
    if result["objective_not_one_sentence"]:
        found.append("OBJECTIVE is more than one sentence: two goals are two agents")
    if result["inputs_not_paths"]:
        found.append("INPUTS holds prose, not paths")
    if result["specs_invalid"]:
        found.append("SPECS paraphrases instead of citing <task-doc>.md#S<n>")
    if result["budget_without_number"]:
        found.append("BUDGET carries no number")
    if result["too_long"]:
        found.append(f"the brief is over {max_lines} lines: pass paths, not content")
    return found


def report(inp: dict, mode: str, kind: str, reason: str) -> None:
    """One ledger line and what this tree shows per mode: block denies, warn
    prints the visible warn, off and log show nothing."""
    if mode == "block":
        c.ledger(inp, HOOK, kind, "deny", mode, reason)
        c.emit_pretool("deny", reason + "." + FIX)
    elif mode in ("off", "log"):  # nothing is shown, so the line says log, never warn
        c.ledger(inp, HOOK, kind, "log", mode, reason)
    else:
        c.ledger(inp, HOOK, kind, "warn", mode, reason)
        c.emit_warn(inp.get("hook_event_name"), kind, f"write the brief from {TEMPLATE} before a launch; {reason}")


def main() -> int:
    inp = c.read_input()
    if inp.get("tool_name") not in TOOLS:
        return 0
    tool_input = inp.get("tool_input") or {}
    target = tool_input.get("subagent_type") or ""
    repo = c.repo_root(inp)

    if c.is_subagent(inp):
        contract = c.contract_for(inp.get("agent_type"), repo)
        if contract is not None and target not in (contract.get("may_spawn") or []):
            reason = f"{inp.get('agent_type') or 'this agent'} may not launch {target or 'an agent'}: its contract's may_spawn does not list it"
            c.ledger(inp, HOOK, "spawn-not-allowed", "deny", "block", reason)
            c.emit_pretool("deny", reason + ". Return the need in your output; the orchestrator launches agents.")
            return 0

    config = c.load_config()
    if not c.rdd_enabled(config):
        return 0
    from lib import brief_check  # noqa: E402  (after the absolute deny, see the module docstring)

    prompt = str(tool_input.get("prompt") or "")
    names = roster(brief_check, repo)
    result = brief_check.check(prompt, roster=names)
    mode = c.hook_mode(config, HOOK)
    if result["verdict"] != "PASS":
        report(inp, mode, "spawn-no-goal",
               "launch without a goal contract (" + "; ".join(problems(result, brief_check.MAX_LINES)) + ")")
        return 0
    role = brief_check.role_name(dict(brief_check.parse(prompt)).get("ROLE", ""))
    if target in names and role != target:
        report(inp, mode, "spawn-role-mismatch", f"the brief's ROLE is {role} but the launched role is {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
