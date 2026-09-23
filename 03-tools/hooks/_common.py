"""What the kit's Claude Code hooks share: read stdin, load the config,
resolve the mode (warn|block), write the ledger and emit decisions. All
stdlib, no network. Golden rule: an exception here never brings down the
session; anything non-absolute fails open (exit 0, empty stdout).

Environment variables a test can set: METODO_TOOLS (kit or instance root),
METODO_PROJECT_CONFIG (alternate project.json), METODO_HOOKS_DIR (where
out/hooks goes), METODO_RDD_DIR (where receipts live).
"""
from __future__ import annotations

import datetime
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

TOOLS_ROOT = Path(os.environ.get("METODO_TOOLS") or Path(__file__).resolve().parent.parent).resolve()
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

DEFAULT_SHARED_BUILD_FILES = ("settings.gradle", "build.gradle", "gradle.properties", "gradle/libs.versions.toml", "app/build.gradle")
CLAUDE_GLOBS = (".claude/**", "**/.claude/**")


def read_input() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_config() -> dict:
    path = Path(os.environ.get("METODO_PROJECT_CONFIG") or TOOLS_ROOT / "config" / "project.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def rdd_enabled(config: dict) -> bool:
    return bool((config.get("rdd") or {}).get("enabled"))


def hook_mode(config: dict, hook: str) -> str:
    rdd = config.get("rdd") or {}
    return (rdd.get("hook_modes") or {}).get(hook) or rdd.get("mode") or "warn"


def is_subagent(inp: dict) -> bool:
    return bool(inp.get("agent_type") or inp.get("agent_id"))


def hooks_dir() -> Path:
    return Path(os.environ.get("METODO_HOOKS_DIR") or TOOLS_ROOT / "out" / "hooks")


def session_dir(inp: dict) -> Path:
    return hooks_dir() / str(inp.get("session_id") or "unknown")


def repo_root(inp: dict) -> Path | None:
    for candidate in (os.environ.get("CLAUDE_PROJECT_DIR"), inp.get("cwd"), os.getcwd()):
        if not candidate:
            continue
        probe = subprocess.run(["git", "-C", candidate, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if probe.returncode == 0:
            return Path(probe.stdout.strip())
    return None


def rel_path(path: str, repo: Path | None) -> str:
    p = Path(path)
    if repo is not None and p.is_absolute():
        try:
            return p.resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            return p.as_posix()
    return p.as_posix()


def glob_match(path: str, pattern: str) -> bool:
    import fnmatch
    if fnmatch.fnmatch(path, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:])


def shared_build_patterns(config: dict) -> list[str]:
    files = list((config or {}).get("shared_build_files") or DEFAULT_SHARED_BUILD_FILES)
    return files + list(CLAUDE_GLOBS)


def contract_for(agent_type: str | None, repo: Path | None) -> dict | None:
    if not agent_type:
        return None
    candidates = []
    if repo is not None:
        candidates.append(repo / ".claude" / "agents" / f"{agent_type}.contract.json")
    candidates.append(TOOLS_ROOT.parent / "01-roles" / "agents" / f"{agent_type}.contract.json")
    candidates.append(TOOLS_ROOT / "claude" / "agents" / f"{agent_type}.contract.json")
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
    return None


def current_tree(repo: Path | None, ref: str = "HEAD") -> str | None:
    if repo is None:
        return None
    probe = subprocess.run(["git", "-C", str(repo), "rev-parse", f"{ref}^{{tree}}"], capture_output=True, text=True)
    return probe.stdout.strip() if probe.returncode == 0 else None


def receipts_dir() -> Path:
    return Path(os.environ.get("METODO_RDD_DIR") or TOOLS_ROOT / "out" / "rdd")


def receipt_for(tree: str | None) -> dict | None:
    if not tree:
        return None
    path = receipts_dir() / f"{tree}.receipt.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def ledger(inp: dict, hook: str, kind: str, decision: str, mode: str, reason: str = "", path: str | None = None,
           tree: str | None = None, receipt: str | None = None, tool: str | None = None) -> None:
    try:
        sdir = session_dir(inp)
        sdir.mkdir(parents=True, exist_ok=True)
        file = sdir / "ledger.jsonl"
        seq = sum(1 for _ in file.open("r", encoding="utf-8")) + 1 if file.exists() else 1
        line = {"seq": seq, "hook": hook, "event": inp.get("hook_event_name"), "agent_type": inp.get("agent_type"),
                "agent_id": inp.get("agent_id"), "tool": tool or inp.get("tool_name"), "kind": kind, "decision": decision,
                "mode": mode, "reason": reason, "path": path, "tree": tree, "receipt": receipt}
        with file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


def write_run_meta(inp: dict) -> None:
    try:
        sdir = session_dir(inp)
        sdir.mkdir(parents=True, exist_ok=True)
        meta = sdir / "run-meta.json"
        if not meta.exists():
            meta.write_text(json.dumps({"started_at": datetime.datetime.now().isoformat(timespec="seconds"),
                                        "host": platform.node(), "session_id": inp.get("session_id")}, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def emit_pretool(decision: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))


def emit_stop_block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


def run_guarded(fn) -> int:
    """Runs the hook; any unexpected failure exits 0 with no stdout (fails
    open), with the trace on stderr for the human ledger."""
    try:
        return int(fn() or 0)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"metodo hook error (fail-open): {exc}", file=sys.stderr)
        return 0
