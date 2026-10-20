#!/usr/bin/env python3
"""PreToolUse Edit|Write|MultiEdit. Absolute (always, even with RDD off): a
subagent never touches shared build files or .claude/**; the main session
gets `ask` on a build file. Non-absolute (warn|block mode): a subagent
outside its may_write or the open receipt's scope.

Main-session writer warn (T7, S2 of odd/tasks/delegation-context.md): a
main-session edit of a source path inside the repo (not exempt_globs,
tests_globs or odd/; a round dir lives outside the repo) while the newest
routing decision for this repo put a writer at `delegate: subagent` gets one
visible METODO-WARN delegate-writer and a ledger line, once per session per
decision (a marker under the session dir). Never a deny or an ask. The log is
$METODO_ROUTING_LOG or <tools>/out/runs/routing.jsonl; the newest line
whose `repo` is absent (an instance serves one repo) or equals this repo
wins. Lines carry per-role counts only, so the writer's delegate is read
from the roster's own `delegate` when present, else inferred: all writers
share one rule (main only on a small task), so fewer main entries than
running writers means the writers are subagents; an ambiguous count stays
silent."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as c  # noqa: E402

HOOK = "guard_paths"
# Mirrors of lib/router.py (WRITER_ROLES, EXPLORER_ROLES) and lib/rdd_risk.py
# (DEFAULT_RDD globs): a hook stays standalone in a partial instance copy.
WRITER_ROLES = ("generic-proposer", "generic-mechanic")
EXPLORER_ROLES = ("generic-cartographer",)
DEFAULT_EXEMPT_GLOBS = ("**/*.md", "docs/**")
DEFAULT_TESTS_GLOBS = ("**/src/test/**", "**/src/androidTest/**")


def _routing_log() -> Path:
    return Path(os.environ.get("METODO_ROUTING_LOG") or c.TOOLS_ROOT / "out" / "runs" / "routing.jsonl")


def _same_repo(value, repo: Path | None) -> bool:
    if not value:
        return True
    if repo is None:
        return False
    try:
        return Path(str(value)).expanduser().resolve() == repo.resolve()
    except OSError:
        return False


def _newest_decision(repo: Path | None) -> tuple[dict, str] | None:
    try:
        lines = _routing_log().read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw in reversed(lines):
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(line, dict) and _same_repo(line.get("repo"), repo):
            return line, raw
    return None


def _delegated_writers(line: dict) -> list[str]:
    """The writer roles the decision put at delegate: subagent, in roster order."""
    running = [e for e in line.get("roster") or [] if isinstance(e, dict) and e.get("launch") == "run"]
    writers = [e for e in running if e.get("role") in WRITER_ROLES]
    if not writers or line.get("status") != "ok":
        return []
    names = list(dict.fromkeys(e["role"] for e in writers))
    if all("delegate" in e for e in writers):
        return list(dict.fromkeys(e["role"] for e in writers if e["delegate"] == "subagent"))
    main = (line.get("delegation") or {}).get("main")
    if not isinstance(main, int):
        return []
    return names if main < len(writers) else []


def _source_path(rel: str, config: dict) -> bool:
    if rel.startswith("/") or rel.startswith("~") or rel.startswith("../") or rel == "odd" or rel.startswith("odd/"):
        return False
    rdd = config.get("rdd") or {}
    globs = list(rdd.get("exempt_globs") or DEFAULT_EXEMPT_GLOBS) + list(rdd.get("tests_globs") or DEFAULT_TESTS_GLOBS)
    return not any(c.glob_match(rel, g) for g in globs)


def main_session_writer_warn(inp: dict, config: dict, repo: Path | None, rel: str) -> None:
    if repo is None or not _source_path(rel, config):
        return
    found = _newest_decision(repo)
    if found is None:
        return
    line, raw = found
    writers = _delegated_writers(line)
    if not writers:
        return
    marker = c.session_dir(inp) / f"delegate-writer-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}.marker"
    if marker.exists():
        return
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(raw + "\n", encoding="utf-8")
    except OSError:
        pass
    rule = line.get("rule") or "?"
    reason = f"routing rule {rule} put {', '.join(writers)} at delegate: subagent; the main session edited {rel}"
    c.ledger(inp, HOOK, "main-edit-delegated-role", "warn", "warn", reason, path=rel)
    c.emit_warn(inp.get("hook_event_name"), "delegate-writer",
                f"routing rule {rule} delegates this edit to {writers[0]} (a subagent); the main session coordinates: "
                f"launch {writers[0]} with a brief, or go on if the owner chose to.")


def main() -> int:
    inp = c.read_input()
    file_path = (inp.get("tool_input") or {}).get("file_path")
    if not file_path:
        return 0
    config = c.load_config()
    repo = c.repo_root(inp)
    rel = c.rel_path(file_path, repo)
    subagent = c.is_subagent(inp)

    hit = c.shared_build_hit(rel, config)
    if hit is not None:
        if subagent:
            c.ledger(inp, HOOK, "forbidden-path", "deny", "block", f"matches {hit}", path=rel)
            c.emit_pretool("deny", f"{rel} is a shared build file or .claude path: agents never edit it (methodology.md paragraph 4). Report it in your output instead.")
            return 0
        if ".claude" not in hit:
            c.ledger(inp, HOOK, "forbidden-path", "ask", "block", f"matches {hit}", path=rel)
            c.emit_pretool("ask", f"{rel} is a shared build file: owner gate.")
            return 0

    if not subagent:
        if hit is None:
            main_session_writer_warn(inp, config, repo, rel)
        return 0
    if not c.rdd_enabled(config):
        return 0

    contract = c.contract_for(inp.get("agent_type"), repo) or {}
    allow = [g for g in contract.get("may_write", []) if "<" not in g]
    receipt = c.receipt_for(c.current_tree(repo))
    if receipt is not None and receipt.get("state") != "finalized":
        allow += receipt.get("scope_globs") or []
    if not allow:
        return 0
    if any(c.glob_match(rel, g) for g in allow):
        return 0
    mode = c.hook_mode(config, HOOK)
    reason = f"{rel} is outside the role's may_write / receipt scope ({', '.join(allow)})"
    if mode == "block":
        c.ledger(inp, HOOK, "scope-outside", "deny", mode, reason, path=rel)
        c.emit_pretool("deny", reason + ". Stay inside the change card's scope boundary.")
    else:
        c.ledger(inp, HOOK, "scope-outside", "warn", mode, reason, path=rel)
        c.emit_warn(inp.get("hook_event_name"), "scope-outside",
                    reason + "; stay inside the change card's scope or report the need in your output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(c.run_guarded(main))
