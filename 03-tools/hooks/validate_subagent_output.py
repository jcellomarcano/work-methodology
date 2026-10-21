#!/usr/bin/env python3
"""Stop in a schema-bearing role's frontmatter (Claude Code turns it into
SubagentStop). Reads last_assistant_message, tolerates fences, validates
against the role's schema. FAIL in block mode: blocks once with the errors
(marker per agent_id); second time, or stop_hook_active: lets it through and
logs it. Never blocks in warn mode. INCOMPLETE (truncated) is logged.

A runtime that cannot send a subagent back (pi's agent_end) passes
"runtime_can_block": false; a FAIL in block mode is then logged as
invalid-unenforced, with no marker and no block. Claude Code never sends the
key, so its behavior is the one above.

Report cap (D9): a final message over
findings_schema_validator.REPORT_CAP_TOKENS (ceil(chars / 4)) is logged as
report-over-cap and, in block mode, blocks once (its own marker) with the
handoff fix; a schema FAIL and an over-cap report in the same turn give one
block naming both. A context_tokens_used above the role contract's
max_context_tokens is logged as context-over-cap and never blocks."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

from lib import findings_schema_validator, round_files  # noqa: E402

HOOK = "validate_subagent_output"
FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> tuple[dict | None, bool]:
    fenced = False
    candidate = text.strip()
    match = FENCE_RE.search(candidate)
    if match:
        candidate, fenced = match.group(1).strip(), True
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end == -1:
        return None, fenced
    try:
        return json.loads(candidate[start:end + 1]), fenced
    except json.JSONDecodeError:
        return None, fenced


def _block_once(inp: dict, name: str) -> bool:
    """True the first time `name` blocks this agent; writes its marker."""
    marker = c.session_dir(inp) / f"{name}-{inp.get('agent_id') or 'unknown'}"
    if marker.exists():
        return False
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("1", encoding="utf-8")
    return True


def _schema_check(inp: dict, mode: str, schema_name: str, verdict: str, errors: list[str]) -> str | None:
    """Ledgers a schema FAIL and returns the block reason when it blocks."""
    if verdict == "INCOMPLETE":
        c.ledger(inp, HOOK, "output-truncated", "log", mode, "truncated:true")
        return None
    if verdict == "PASS":
        return None
    if mode == "block" and inp.get("runtime_can_block") is False:
        c.ledger(inp, HOOK, "output-invalid", "invalid-unenforced", mode, "; ".join(errors)[:500])
        return None
    if mode == "block" and _block_once(inp, "output-blocked"):
        c.ledger(inp, HOOK, "output-invalid", "block", mode, "; ".join(errors)[:500])
        return f"Your final message must be JSON valid against {schema_name}.schema.json. Errors: " + "; ".join(errors)[:800]
    shown = "log" if mode in ("off", "log") else "warn"  # nothing is shown at off/log (T19)
    c.ledger(inp, HOOK, "output-invalid", shown if mode != "block" else "invalid-let-through", mode, "; ".join(errors)[:500])
    return None


def _report_cap_check(inp: dict, mode: str, message: str) -> str | None:
    """Ledgers a report over the D9 cap and returns the block reason when it blocks."""
    fsv = findings_schema_validator
    tokens = fsv.report_over_cap(message)
    if tokens is None:
        return None
    reason = f"{tokens} tokens > {fsv.REPORT_CAP_TOKENS} (ceil(chars/4))"
    if mode != "block":
        decision = "log" if mode in ("off", "log") else "warn"
    elif inp.get("runtime_can_block") is False:
        decision = "over-cap-unenforced"
    elif _block_once(inp, "report-over-cap-blocked"):
        c.ledger(inp, HOOK, "report-over-cap", "block", mode, reason)
        return f"Your final report is {tokens} tokens, over the {fsv.REPORT_CAP_TOKENS:,}-token cap: {fsv.REPORT_CAP_FIX}."
    else:
        decision = "over-cap-let-through"
    c.ledger(inp, HOOK, "report-over-cap", decision, mode, reason)
    return None


def _context_check(inp: dict, mode: str, agent_type: str, document) -> None:
    """context_tokens_used above the contract's max_context_tokens: a measurement, logged, never blocked."""
    if not isinstance(document, dict) or "context_tokens_used" not in document:
        return
    contract = c.contract_for(agent_type, c.repo_root(inp)) or {}
    cap = contract.get("max_context_tokens")
    used = findings_schema_validator.context_over_cap(document, cap)
    if used is not None:
        c.ledger(inp, HOOK, "context-over-cap", "log", mode, f"context_tokens_used {used} > max_context_tokens {cap}")


def main() -> int:
    inp = c.read_input()
    agent_type = inp.get("agent_type")
    if not agent_type or agent_type not in round_files.ROLE_SCHEMA or inp.get("stop_hook_active"):
        return 0
    config = c.load_config()
    if not c.rdd_enabled(config):
        return 0
    mode = c.hook_mode(config, HOOK)
    schema_name = round_files.ROLE_SCHEMA[agent_type]
    message = inp.get("last_assistant_message") or ""
    document, fenced = extract_json(message)
    if document is None:
        errors = ["final message is not a JSON object"]
        verdict = "FAIL"
    else:
        result = findings_schema_validator.validate(document, round_files.load_schema(schema_name))
        errors, verdict = result["errors"], result["verdict"]
    if fenced:
        c.ledger(inp, HOOK, "output-fenced", "log", mode, "JSON inside fences")
    blocks = [reason for reason in (_schema_check(inp, mode, schema_name, verdict, errors),
                                    _report_cap_check(inp, mode, message)) if reason]
    _context_check(inp, mode, agent_type, document)
    if blocks:
        c.emit_stop_block(" ".join(blocks))
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
