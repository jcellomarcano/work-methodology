#!/usr/bin/env python3
"""Stop in a schema-bearing role's frontmatter (Claude Code turns it into
SubagentStop). Reads last_assistant_message, tolerates fences, validates
against the role's schema. FAIL in block mode: blocks once with the errors
(marker per agent_id); second time, or stop_hook_active: lets it through and
logs it. Never blocks in warn mode. INCOMPLETE (truncated) is logged."""
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
    document, fenced = extract_json(inp.get("last_assistant_message") or "")
    if document is None:
        errors = ["final message is not a JSON object"]
        verdict = "FAIL"
    else:
        result = findings_schema_validator.validate(document, round_files.load_schema(schema_name))
        errors, verdict = result["errors"], result["verdict"]
    if fenced:
        c.ledger(inp, HOOK, "output-fenced", "log", mode, "JSON inside fences")
    if verdict == "INCOMPLETE":
        c.ledger(inp, HOOK, "output-truncated", "log", mode, "truncated:true")
        return 0
    if verdict == "PASS":
        return 0
    marker = c.session_dir(inp) / f"output-blocked-{inp.get('agent_id') or 'unknown'}"
    if mode == "block" and not marker.exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1", encoding="utf-8")
        c.ledger(inp, HOOK, "output-invalid", "block", mode, "; ".join(errors)[:500])
        c.emit_stop_block(f"Your final message must be JSON valid against {schema_name}.schema.json. Errors: " + "; ".join(errors)[:800])
        return 0
    c.ledger(inp, HOOK, "output-invalid", "warn" if mode != "block" else "invalid-let-through", mode, "; ".join(errors)[:500])
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
