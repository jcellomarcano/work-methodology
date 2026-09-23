#!/usr/bin/env python3
"""PreToolUse Bash (and the receipt_start|finalize|acknowledge MCP tools);
PostToolUse Bash only logs. Absolute: `git push --force` without lease is
always denied; a subagent never pushes, opens a PR, merges, tags, or
opens/closes/acknowledges receipts. Non-absolute (RDD): in the main session a
push/PR/merge without an approved receipt for the pushed tree warns or asks
(block); --no-verify, --amend and rebase are only logged."""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

HOOK = "guard_gates"
# Each command is split into segments (| ; && || and line breaks) and only
# the command word of each segment is checked: an `echo '... git push ...'`
# is not a push. Guardrail, not a sandbox: `bash -c "git push"` is invisible
# to it, and the ledger measures what slips through.
SEGMENT_SPLIT = re.compile(r"\|\||&&|[|;\n]")
PREFIX = r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*(?:command\s+|sudo\s+|time\s+)?"
GIT = PREFIX + r"git\s+(?:-C\s+\S+\s+)?(?:--?[A-Za-z-]+(?:=\S+)?\s+)*"
GATES = (
    ("gate-push", re.compile(GIT + r"push\b(?P<rest>.*)$")),
    ("gate-pr", re.compile(PREFIX + r"gh\s+pr\s+(create|merge)\b")),
    ("gate-merge", re.compile(GIT + r"merge\b")),
    ("gate-tag", re.compile(GIT + r"tag\s+(?!-l|--list)(-a|-s|-m|-f|[A-Za-z0-9])")),
    ("gate-receipt", re.compile(PREFIX + r"(?:python3?\s+)?\S*rdd_receipt\.py\s+(?:--\S+\s+\S+\s+)*(start|finalize|acknowledge)\b")),
)
LOG_ONLY = (
    ("no-verify", re.compile(GIT + r"(?:push|commit)\b.*--no-verify")),
    ("amend", re.compile(GIT + r"commit\b.*--amend")),
    ("rebase", re.compile(GIT + r"rebase\b")),
)
FORCE_RE = re.compile(r"(^|\s)(--force|-f)(\s|$)")
LEASE_RE = re.compile(r"--force-with-lease|--force-if-includes")
INTEGRATION_BRANCHES = ("develop", "master", "main", "release")


HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\1(?=\n|$)", re.DOTALL)


def strip_heredocs(command: str) -> str:
    """A heredoc's body is data (a file being written), not a command: a
    `git push --force` line inside a README is not a push."""
    return HEREDOC_RE.sub("<<HEREDOC", command or "")


def segments(command: str) -> list[str]:
    return [seg for seg in SEGMENT_SPLIT.split(strip_heredocs(command)) if seg.strip()]


def push_segments(command: str) -> list[re.Match]:
    return [m for seg in segments(command) if (m := GATES[0][1].match(seg))]


def is_force_push(command: str) -> bool:
    for match in push_segments(command):
        rest = match.group("rest")
        if FORCE_RE.search(rest) and not LEASE_RE.search(rest):
            return True
    return False


def pushed_ref(command: str) -> str:
    for match in push_segments(command):
        try:
            words = [w for w in shlex.split(match.group("rest"), posix=True) if not w.startswith("-")]
        except ValueError:
            words = []
        if len(words) >= 2:
            return words[1].split(":")[0] or "HEAD"
    return "HEAD"


def classify(command: str, tool_name: str) -> list[str]:
    if tool_name.startswith("mcp__metodo__receipt_"):
        return ["gate-receipt"]
    kinds = []
    for seg in segments(command):
        for kind, regex in GATES:
            if regex.match(seg):
                if kind == "gate-merge" and not any(b in seg for b in INTEGRATION_BRANCHES):
                    continue
                if kind not in kinds:
                    kinds.append(kind)
    return kinds


def log_only_kinds(command: str) -> list[str]:
    return [kind for kind, regex in LOG_ONLY if any(regex.match(seg) for seg in segments(command))]


def main() -> int:
    inp = c.read_input()
    tool_name = inp.get("tool_name") or ""
    command = (inp.get("tool_input") or {}).get("command") or ""
    event = inp.get("hook_event_name")
    subagent = c.is_subagent(inp)

    if tool_name == "Bash" and is_force_push(command):
        if event == "PreToolUse":
            c.ledger(inp, HOOK, "force-push", "deny", "block", "git push --force without --force-with-lease")
            c.emit_pretool("deny", "git push --force is never allowed: use --force-with-lease (methodology.md paragraph 6).")
        return 0

    kinds = classify(command, tool_name)
    if not kinds:
        if event == "PreToolUse":
            for kind in log_only_kinds(command):
                c.ledger(inp, HOOK, kind, "log", "log", "")
        return 0

    if subagent:
        if event == "PreToolUse":
            c.ledger(inp, HOOK, kinds[0], "deny", "block", "subagents never deliver or open/close receipts")
            c.emit_pretool("deny", "Delivery (push, PR, merge, tag) and receipt start/finalize/acknowledge are the owner's: report it in your output.")
        return 0

    config = c.load_config()
    if not c.rdd_enabled(config):
        return 0
    repo = c.repo_root(inp)
    tree = c.current_tree(repo, pushed_ref(command) if "gate-push" in kinds else "HEAD")
    receipt = c.receipt_for(tree)
    receipt_state = (receipt or {}).get("verdict") or ("open" if receipt else "none")
    kind = kinds[0]

    if event == "PostToolUse":
        c.ledger(inp, HOOK, kind + "-outcome", "ran", c.hook_mode(config, HOOK), "", tree=tree, receipt=receipt_state)
        return 0
    if kind == "gate-receipt":
        c.ledger(inp, HOOK, kind, "allow", "log", "owner session", tree=tree, receipt=receipt_state)
        return 0

    mode = c.hook_mode(config, HOOK)
    if receipt_state == "approved":
        c.ledger(inp, HOOK, kind, "allow", mode, "receipt approved", tree=tree, receipt=receipt_state)
        return 0
    reason = f"no approved receipt for tree {tree[:12] if tree else '?'} (receipt: {receipt_state})"
    if mode == "block":
        c.ledger(inp, HOOK, kind, "ask", mode, reason, tree=tree, receipt=receipt_state)
        c.emit_pretool("ask", reason + ". Run receipt-review first, or confirm to deliver without receipt (it will be recorded).")
    else:
        c.ledger(inp, HOOK, kind, "warn", mode, reason, tree=tree, receipt=receipt_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
