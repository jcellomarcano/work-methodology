#!/usr/bin/env python3
"""Stop (main session) and SubagentStop (writer roles): the done gate before
the person reads "done" (T14, WU17; done-gate.md section 4; owner decision D2).

Reads `last_assistant_message`. No done claim (lib/done_check.detect_claims):
silent, nothing written. Otherwise lib/done_check.py runs in-process over the
repo, the session dir (touched.jsonl; ledger.jsonl with the owner waivers),
runs.jsonl (METODO_RUNS_DIR or <tools>/out/runs) and done-gate.json
(METODO_DONE_GATE_CONFIG, else beside project.json, else <tools>/config).
Every rule PASS or SKIP: silent. Any FLAG, BLOCK or WAIVED rule is a fire:
one ledger line with each rule id and status, and the DONE-GATE block shown.

Warn first (D2): the block is shown as `systemMessage`, the Stop events'
visible field (context-method.md section 5); nothing is stopped. Blocking is
per rule, never by profile: only a rule whose mode in done-gate.json is BLOCK
(and not waived) sends the agent back (`decision: block`, the block as the
reason), at most once per worktree_sha (marker under the session dir). The
next stop on the same worktree, or one with stop_hook_active, is let through
and ledgered `done-unproven`. A runtime that cannot send the agent back
(pi's agent_end passes `runtime_can_block: false`) records `done-unproven`
`unenforced` instead.

Hook mode (_common.hook_mode): off, silent; log, ledger only; warn or block,
shown (block does not raise a FLAG rule). RDD off: silent.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

from lib import done_check  # noqa: E402

HOOK = "done_gate"
# Mirror of lib/router.py WRITER_ROLES (like hooks/guard_paths.py).
WRITER_ROLES = ("generic-proposer", "generic-mechanic")
SEND_BACK = ("\nFix each BLOCK line, or paste this DONE-GATE block verbatim in your reply and say what stays "
             "unproven; only the owner waives a rule (03-tools/bin/done-waive.sh).")


def gate_config_path() -> Path:
    explicit = os.environ.get("METODO_DONE_GATE_CONFIG")
    if explicit:
        return Path(explicit)
    project = os.environ.get("METODO_PROJECT_CONFIG")
    beside = Path(project).parent / "done-gate.json" if project else None
    return beside if beside and beside.is_file() else done_check.DEFAULT_CONFIG


def check(inp: dict, repo: Path, message: str, config_path: Path) -> dict:
    """done_check over the message itself (run's `reply`, so --reply is never read)."""
    args = done_check._parser().parse_args(["--repo", str(repo), "--reply", "-", "--config", str(config_path),
                                            "--receipts", str(c.receipts_dir()), "--session-dir", str(c.session_dir(inp))])
    payload, _ = done_check.run(args, reply=message)
    return payload


def _marker(inp: dict, worktree_sha: str) -> Path:
    who = inp.get("agent_id") or "main"
    return c.session_dir(inp) / f"done-gate-blocked-{who}-{(worktree_sha or 'none')[:16]}"


def main() -> int:
    inp = c.read_input()
    event = inp.get("hook_event_name") or "Stop"
    if c.is_subagent(inp):
        if inp.get("agent_type") not in WRITER_ROLES:
            return 0
    elif event == "SubagentStop":
        return 0
    message = inp.get("last_assistant_message") or ""
    if not message.strip():
        return 0
    config = c.load_config()
    if not c.rdd_enabled(config):
        return 0
    mode = c.hook_mode(config, HOOK)
    if mode == "off":
        return 0
    config_path = gate_config_path()
    try:
        gate = done_check.load_config(config_path)
    except (OSError, ValueError):
        return 0
    if not done_check.detect_claims(message, gate):
        return 0
    repo = c.repo_root(inp)
    if repo is None:
        return 0
    try:
        payload = check(inp, repo, message, config_path)
    except done_check.UsageError:
        return 0
    rules = payload["rules"]
    fired = [r for r in rules if r["status"] in ("FLAG", "BLOCK")]
    if not fired:
        return 0
    blocking = [r for r in fired if r["status"] == "BLOCK" and not r.get("waiver")]
    reason = " ".join(f"{r['id']}:{'WAIVED' if r.get('waiver') else r['status']}" for r in fired)
    reason += f" · claims {','.join(payload['claims'])} · worktree {(payload['worktree_sha'] or 'none')[:12]}"
    block = payload["flag_block"]
    tree = payload["tree_sha"]

    if mode == "log":
        c.ledger(inp, HOOK, "done-gate", "log", mode, reason, tree=tree)
        return 0
    if not blocking:
        c.ledger(inp, HOOK, "done-gate", "warn", mode, reason, tree=tree)
        c.emit_stop_message(block)
        return 0
    if inp.get("runtime_can_block") is False:
        c.ledger(inp, HOOK, "done-unproven", "unenforced", mode, reason, tree=tree)
        c.emit_stop_message(block)
        return 0
    marker = _marker(inp, payload["worktree_sha"])
    if inp.get("stop_hook_active") or marker.exists():
        c.ledger(inp, HOOK, "done-unproven", "let-through", mode, reason, tree=tree)
        c.emit_stop_message(block)
        return 0
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1", encoding="utf-8")
    except OSError:
        c.ledger(inp, HOOK, "done-unproven", "let-through", mode, reason + " · marker not writable", tree=tree)
        c.emit_stop_message(block)
        return 0
    c.ledger(inp, HOOK, "done-gate", "block", mode, reason, tree=tree)
    c.emit_stop_block(block + SEND_BACK)
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
