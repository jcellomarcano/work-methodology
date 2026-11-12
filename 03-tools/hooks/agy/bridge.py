#!/usr/bin/env python3
"""The kit's guards on agy (Google Antigravity CLI).

agy runs `hooks.json` commands with its own stdin (camelCase, `toolCall`) and
reads its own stdout decision. This file is the adapter, not a second
implementation: it turns agy's stdin into the stdin Claude Code sends, runs
the same hooks/*.py unchanged, and turns their stdout back into agy's protocol.

    bridge.py <SessionStart|PreToolUse|PostToolUse|Stop>   (agy stdin on stdin)

Which script runs on which tool is read from hooks/hooks.settings.json at run
time. ROWS and EXEMPT below say, entry by entry, how agy reaches it or why it
does not; tests/test_agy_bridge.py fails when an entry has neither.

Measured on agy 1.4.7 (odd/tasks/agy-adapter.md L3, Spanish tree, 2026-10-26):

- PreToolUse: an empty stdout is neutral; `{}` denies (decision is required);
  a nonzero exit fails the tool; `allow` would bypass agy's own permissions.
  So the bridge prints only a script's deny or ask, and always exits 0.
- An owner gate (`ask`) becomes `force_ask`, because a plain `ask` lets edits
  through in accept-edits mode. Inside a subagent nobody can answer, so it is
  a deny that tells the subagent to report it.
- A subagent is its own conversation and its hooks carry no agent type. Its
  transcript opens with a system message `sender=<parent> ... content=<prompt>`;
  the parent's `invoke_subagent` call is recorded with its TypeName and prompt,
  and the pair names the role. A sender without a recorded call is still a
  subagent ("agy-subagent"): the subagent rules apply, contracts do not.
- Stop: a script's `block` becomes `continue`, which sends the agent back.
  agy has no SubagentStop: a Stop inside a subagent's conversation is the
  kit's SubagentStop.

What a script prints, and what agy gets:

    permissionDecision deny       PreToolUse   {"decision": "deny", "reason"}
    permissionDecision ask        PreToolUse   force_ask (owner), deny (subagent)
    permissionDecision allow      PreToolUse   nothing, never passed on
    additionalContext (a warn)    PreToolUse   nothing: see below
    anything                      PostToolUse  nothing: the scripts only record
    decision block                Stop         {"decision": "continue", "reason"}
    systemMessage (a warn)        Stop         nothing: see below
    the status text               SessionStart injectSteps systemMessage

Not measured on agy 1.4.7, so not used: a PreToolUse or Stop output that
reaches the model without a decision. The visible METODO-WARN line and the
done gate's warn-first block therefore stay in the ledger only, where the
script already wrote them.

TOOLS root: METODO_TOOLS, else this file's grandparent. Repo: METODO_REPO,
else agy's first workspace path.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
TOOLS_ROOT = Path(os.environ.get("METODO_TOOLS") or HOOKS.parent)
sys.path.insert(0, str(HOOKS))
import _common as c  # noqa: E402

SCRIPT_RE = re.compile(r"\$H/([A-Za-z0-9_]+\.py)")
SENDER_RE = re.compile(r"sender=(\S+).*?content=(.*?)(?:\n</SYSTEM_MESSAGE>|$)", re.S)
ROLE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
UNKNOWN_SUBAGENT = "agy-subagent"
# Any other tool that names a Path and sounds like a write is gated as an Edit.
WRITE_LIKE = re.compile(r"write|edit|replace|create|delete|move|rename", re.I)
DEFAULT_TIMEOUT = 10
# Seconds each agy event may spend in scripts: 2 under its timeout in hooks/agy/hooks.json.
BUDGET_S = {"SessionStart": 13, "PreToolUse": 33, "PostToolUse": 23, "Stop": 33}
# Not in hooks.settings.json: on Claude Code it travels in each schema-bearing
# role's frontmatter. An agy subagent carries no hooks, so the bridge runs it.
FRONTMATTER_STOP = ("validate_subagent_output.py", DEFAULT_TIMEOUT)

_GATES = "Bash|mcp__metodo__receipt_start|mcp__metodo__receipt_finalize|mcp__metodo__receipt_acknowledge"
_WRITES = "Edit|Write|MultiEdit"

# Parity with hooks/hooks.settings.json, one key per entry: (event, matcher, script).
# ROWS: how agy reaches the entry. EXEMPT: why it does not; an exempt script never runs.
ROWS: dict[tuple[str, str, str], str] = {
    ("PreToolUse", _WRITES, "guard_paths.py"):
        "agy PreToolUse on write_file (Write), edit_file (Edit) and any other write-like tool with a Path (Edit)",
    ("PreToolUse", _GATES, "guard_gates.py"):
        "agy PreToolUse on run_command (Bash) and on call_mcp_tool of the kit server (mcp__metodo__<ToolName>)",
    ("PreToolUse", "Task|Agent", "guard_spawn.py"):
        "agy PreToolUse on invoke_subagent, as a Task launch: TypeName is subagent_type, Prompt is prompt",
    ("PreToolUse", "", "budget.py"):
        "agy PreToolUse on every tool call, with the subagent's resolved role and conversation",
    ("PostToolUse", "Bash", "guard_gates.py"):
        "agy PostToolUse on run_command (Bash): the outcome line, nothing printed",
    ("PostToolUse", _WRITES, "touched_paths.py"):
        "agy PostToolUse on write_file, edit_file and write-like tools: the touched path, nothing printed",
    ("PostToolUse", "mcp__metodo__output_write", "output_author.py"):
        "agy PostToolUse on call_mcp_tool output_write of the kit server, with Arguments as the input",
    ("PostToolUse", _WRITES, "output_author.py"):
        "agy PostToolUse on write_file, edit_file and write-like tools: a round output written by hand",
    ("Stop", "", "done_gate.py"):
        "agy Stop in the owner's conversation, with the last reply read from the transcript",
    ("SubagentStop", "", "done_gate.py"):
        "agy Stop inside a subagent's conversation: agy has no SubagentStop, a subagent is its own conversation",
    ("SessionStart", "startup|resume|compact|clear", "session_start_status.py"):
        "agy SessionStart of the owner's conversation, always as source startup",
}
EXEMPT: dict[tuple[str, str, str], str] = {
    ("PostToolUse", "Bash", "tool_output_filter.py"):
        "Unknown on agy 1.4.7: L2, L3 and L5 name neither a PostToolUse stdin field holding the command "
        "output (the script reads tool_response) nor a stdout field that replaces it (it answers with "
        "updatedToolOutput), so the script would get nothing and could change nothing",
    ("SessionEnd", "", "bench_queue.py"):
        "agy 1.4.7 has no SessionEnd event (Measured, odd/tasks/agy-adapter.md L3). The measurement is "
        "Claude Code only either way: it reads Claude Code transcripts and an agy session writes none, "
        "so a queued agy session would give the collector nothing to measure",
}


def script_of(command: str) -> str:
    match = SCRIPT_RE.search(command or "")
    return match.group(1) if match else ""


def settings_entries(settings: dict) -> list[tuple[str, str, str, int]]:
    """(event, matcher, script, timeout) for every hook of every entry, in file order."""
    return [(event, entry.get("matcher", ""), script_of(hook.get("command", "")), int(hook.get("timeout") or DEFAULT_TIMEOUT))
            for event, entries in (settings.get("hooks") or {}).items() for entry in entries for hook in entry.get("hooks", [])]


def read_settings() -> dict:
    return json.loads((HOOKS / "hooks.settings.json").read_text(encoding="utf-8"))


def load_matrix() -> dict[str, list[tuple[str, str, int]]]:
    matrix: dict[str, list[tuple[str, str, int]]] = {}
    for event, matcher, script, timeout in settings_entries(read_settings()):
        matrix.setdefault(event, []).append((matcher, script, timeout))
    return matrix


def parity_gaps(settings: dict | None = None) -> dict[str, list[tuple[str, str, str]]]:
    """Entries with neither a row nor an exemption, rows or exemptions for an
    entry that is gone, and keys listed as both. All empty means parity."""
    entries = [entry[:3] for entry in settings_entries(read_settings() if settings is None else settings)]
    known = set(ROWS) | set(EXEMPT)
    return {"missing": [entry for entry in entries if entry not in known],
            "stale": sorted(known - set(entries)),
            "both": sorted(set(ROWS) & set(EXEMPT))}


def scripts_for(event: str, name: str) -> list[tuple[str, int]]:
    """The scripts of a kit event whose matcher takes `name` (a Claude tool
    name, a SessionStart source, an agent type), with each one's timeout. An
    entry with no row still runs: only a stated exemption keeps a script out."""
    return [(script, timeout) for matcher, script, timeout in load_matrix().get(event, [])
            if script and (event, matcher, script) not in EXEMPT
            and (matcher == "" or re.fullmatch(f"(?:{matcher})", name))]


def mcp_arguments(value) -> dict:
    """agy's Arguments as the kit tool's input. Which shape agy sends is not
    measured: a JSON text is parsed, and any other shape is an empty input, so
    the gates still judge the call by its name instead of the bridge failing
    open on it."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return dict(value) if isinstance(value, dict) else {}


def claude_call(name: str, args: dict) -> tuple[str, dict]:
    """The Claude tool name and input the hook scripts match on.

    invoke_subagent{TypeName, Prompt, Role} is a Task launch: TypeName is the
    launched role (subagent_type) and Prompt is the brief (prompt), so
    guard_spawn.py judges both. Role stays in the input under its own key and
    maps onto nothing the gate reads: what agy does with it is not measured,
    and the brief's ROLE is the `ROLE:` line of Prompt, never this argument."""
    args = dict(args or {})
    if name == "run_command":
        return "Bash", {**args, "command": args.get("CommandLine", "")}
    if name == "write_file":
        return "Write", {**args, "file_path": args.get("Path", ""), "content": args.get("Content", "")}
    if name == "edit_file":
        return "Edit", {**args, "file_path": args.get("Path", ""), "old_string": args.get("Target", ""),
                        "new_string": args.get("Replacement", "")}
    if name in ("read_file", "view_file"):
        return "Read", {**args, "file_path": args.get("Path", "")}
    if name == "invoke_subagent":
        return "Task", {**args, "subagent_type": str(args.get("TypeName") or ""), "prompt": str(args.get("Prompt") or "")}
    if name == "call_mcp_tool":
        server = str(args.get("ServerName") or "")
        if server == "metodo" or server.endswith("_metodo"):
            server = "metodo"
        return f"mcp__{server}__{args.get('ToolName', '')}", mcp_arguments(args.get("Arguments"))
    if args.get("Path") and WRITE_LIKE.search(name):
        return "Edit", {**args, "file_path": args.get("Path", "")}
    return name, args


def state_dir() -> Path:
    return c.hooks_dir() / "agy"


def record_invocation(parent: str, type_name: str, prompt: str) -> None:
    if not ROLE_NAME.match(type_name or ""):
        return
    path = state_dir() / "invocations.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"parent": parent, "type": type_name, "prompt": (prompt or "").strip()}, ensure_ascii=False) + "\n")


def first_step(transcript_path: str) -> dict | None:
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            line = fh.readline()
        return json.loads(line) if line.strip() else None
    except (OSError, ValueError):
        return None


def role_from_invocations(parent: str, prompt: str) -> str:
    path = state_dir() / "invocations.jsonl"
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        rows = []
    for row in reversed(rows):
        if row.get("parent") == parent and row.get("prompt") == prompt.strip():
            return row.get("type") or UNKNOWN_SUBAGENT
    return UNKNOWN_SUBAGENT


def agent_type(conversation: str, transcript_path: str) -> str:
    """"" for the owner's session, the role name for a subagent."""
    cache = state_dir() / "conversations" / f"{conversation}.json"
    try:
        return json.loads(cache.read_text(encoding="utf-8"))["agent_type"]
    except (OSError, ValueError, KeyError):
        pass
    step = first_step(transcript_path)
    if step is None:
        return ""
    content = str(step.get("content") or "")
    match = SENDER_RE.search(content) if step.get("type") == "SYSTEM_MESSAGE" else None
    if match:
        role = role_from_invocations(match.group(1), match.group(2))
    else:
        # a system message from another conversation that does not parse is still a subagent: fail closed
        role = UNKNOWN_SUBAGENT if step.get("type") == "SYSTEM_MESSAGE" and "sender=" in content else ""
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"agent_type": role}), encoding="utf-8")
    return role


def last_reply(transcript_path: str) -> str:
    text = ""
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("type") == "PLANNER_RESPONSE" and isinstance(row.get("content"), str) and row["content"].strip():
                    text = row["content"]
    except OSError:
        return ""
    return text


def run_script(script: str, payload: dict, repo: str, timeout: float = DEFAULT_TIMEOUT, deadline: float | None = None) -> str:
    """The script's stdout, or "" when it is missing, fails, or the event's
    time is spent: the kit's rule is that a guard never takes the session down."""
    path = HOOKS / script
    if not path.is_file():
        return ""
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0:
            return ""
    env = dict(os.environ, METODO_TOOLS=str(TOOLS_ROOT), METODO_REPO=repo, CLAUDE_PROJECT_DIR=repo)
    try:
        proc = subprocess.run(["python3", str(path)], input=json.dumps(payload), capture_output=True, text=True,
                              env=env, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout or ""


def verdicts(stdout: str) -> list[dict]:
    """Every JSON object a script printed: the whole stdout, else one per line
    (a warn line beside a deny line must not turn the deny into nothing)."""
    text = (stdout or "").strip()
    if not text:
        return []
    try:
        whole = json.loads(text)
    except ValueError:
        whole = None
    if isinstance(whole, dict):
        return [whole]
    found = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            found.append(row)
    return found


def pretool_output(stdout: str, subagent: bool) -> dict | None:
    """agy's decision for one script's stdout. A deny wins over an ask; `allow`
    and a warn's additionalContext give nothing (module docstring)."""
    gate = None
    for row in verdicts(stdout):
        specific = row.get("hookSpecificOutput")
        if not isinstance(specific, dict):
            continue
        decision, reason = specific.get("permissionDecision"), str(specific.get("permissionDecisionReason") or "")
        if decision == "deny":
            return {"decision": "deny", "reason": reason}
        if decision == "ask":
            if subagent:
                return {"decision": "deny", "reason": f"{reason} (owner gate: report it in your output, the parent session decides)"}
            gate = gate or {"decision": "force_ask", "reason": reason}
    return gate


def status_text(stdout: str) -> str:
    """The status script prints plain lines, or additionalContext JSON when it adds the goal anchor."""
    text = (stdout or "").strip()
    for row in verdicts(text):
        specific = row.get("hookSpecificOutput")
        if isinstance(specific, dict) and isinstance(specific.get("additionalContext"), str):
            return specific["additionalContext"].strip()
    return text


def session_start_output(stdout: str) -> dict | None:
    """The status as agy's injected system message (measured: it reaches the model)."""
    text = status_text(stdout)
    return {"injectSteps": [{"systemMessage": {"systemMessage": text}}]} if text else None


def stop_output(stdout: str) -> dict | None:
    for row in verdicts(stdout):
        if row.get("decision") == "block":
            return {"decision": "continue", "reason": str(row.get("reason") or "")}
    return None


def handle(event: str, inp: dict) -> dict | None:
    if event not in BUDGET_S:
        return None
    deadline = time.monotonic() + BUDGET_S[event]
    # agy generates the id; cleaned anyway, since the scripts join it into a path
    conversation = re.sub(r"[^A-Za-z0-9_-]", "_", str(inp.get("conversationId") or "agy-unknown"))
    transcript = str(inp.get("transcriptPath") or "")
    repo = os.environ.get("METODO_REPO") or next(iter(inp.get("workspacePaths") or []), "") or os.getcwd()
    base = {"session_id": conversation, "cwd": repo, "transcript_path": transcript, "hook_event_name": event}

    if event == "SessionStart":
        # A subagent starts with no user input; its status line is the parent's.
        if not inp.get("lastUserInput"):
            return None
        source = "startup"  # agy's SessionStart stdin names no source
        payload = {**base, "source": source, "agent_type": "", "agent_id": ""}
        texts = [status_text(run_script(script, payload, repo, timeout, deadline)) for script, timeout in scripts_for(event, source)]
        return session_start_output("\n".join(text for text in texts if text))

    role = agent_type(conversation, transcript)
    who = {"agent_type": role, "agent_id": conversation if role else ""}

    if event in ("PreToolUse", "PostToolUse"):
        call = inp.get("toolCall") or {}
        tool_name, tool_input = claude_call(str(call.get("name") or ""), call.get("args") or {})
        payload = {**base, **who, "tool_name": tool_name, "tool_input": tool_input}
        if event == "PostToolUse":
            for script, timeout in scripts_for(event, tool_name):
                run_script(script, payload, repo, timeout, deadline)
            return None
        gate = None
        for script, timeout in scripts_for(event, tool_name):
            verdict = pretool_output(run_script(script, payload, repo, timeout, deadline), bool(role))
            if verdict and verdict["decision"] == "deny":
                return verdict
            gate = gate or verdict
        if gate is None and tool_name == "Task":
            record_invocation(conversation, tool_input.get("subagent_type", ""), tool_input.get("prompt", ""))
        return gate

    # Stop: the owner's conversation is the kit's Stop, a subagent's is its SubagentStop.
    text = last_reply(transcript)
    if not text:
        return None
    kit_event = "SubagentStop" if role else "Stop"
    payload = {**base, **who, "hook_event_name": kit_event, "last_assistant_message": text,
               "stop_hook_active": int(inp.get("executionNum") or 0) > 0, "runtime_can_block": True}
    scripts = ([FRONTMATTER_STOP] if role else []) + scripts_for(kit_event, role)
    reasons = []
    for script, timeout in scripts:
        verdict = stop_output(run_script(script, payload, repo, timeout, deadline))
        if verdict:
            reasons.append(verdict["reason"])
    return {"decision": "continue", "reason": "\n".join(reasons)} if reasons else None


def main(argv: list[str]) -> int:
    try:
        event = argv[1] if len(argv) > 1 else ""
        inp = json.loads(sys.stdin.read() or "{}")
        if not isinstance(inp, dict):
            return 0
        out = handle(event, inp)
    except Exception as exc:  # a guard never takes the session down
        print(f"metodo agy bridge: {exc!r}", file=sys.stderr)
        return 0
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
