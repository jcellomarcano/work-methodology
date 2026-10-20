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

try:
    from lib import build_files  # noqa: E402
except ImportError:  # a partial instance copy: the absolute build-file deny must not fail open
    import fnmatch as _fnmatch
    import posixpath as _posixpath
    import types as _types

    # Mirror of lib/build_files.py, pinned by tests/test_gradle_guard.py.
    _GLOBS = ("**/*.gradle", "**/*.gradle.kts", "**/gradle.properties", "**/gradlew", "**/gradlew.bat",
              "**/gradle/wrapper/**", "**/gradle/*.versions.toml", "**/gradle/verification-metadata.xml",
              "**/gradle/verification-keyring.*", "**/gradle/gradle-daemon-jvm.properties", "**/gradle.lockfile",
              "**/settings-gradle.lockfile", "**/gradle/dependency-locks/**", "**/buildSrc/**", "**/build-logic/**")

    def _normalize(path):
        text = str(path).replace("\\", "/")
        if not text:
            return text
        text = _posixpath.normpath(text)
        return "" if text == "." else text

    def _glob_match(path, pattern):
        candidate, pattern = _normalize(path).casefold(), str(pattern).casefold()
        return _fnmatch.fnmatchcase(candidate, pattern) or (
            pattern.startswith("**/") and _fnmatch.fnmatchcase(candidate, pattern[3:]))

    def _first_match(path, patterns):
        return next((p for p in patterns if _glob_match(path, p)), None)

    def _shared_build_files(config):
        configured = (config or {}).get("shared_build_files") if isinstance(config, dict) else None
        return list(configured or _GLOBS)

    build_files = _types.SimpleNamespace(DEFAULT_SHARED_BUILD_FILES=_GLOBS, GRADLE_BUILD_GLOBS=_GLOBS,
                                         normalize=_normalize, glob_match=_glob_match, first_match=_first_match,
                                         shared_build_files=_shared_build_files)

DEFAULT_SHARED_BUILD_FILES = build_files.DEFAULT_SHARED_BUILD_FILES
CLAUDE_GLOBS = (".claude/**", "**/.claude/**")


_INPUT: dict = {}  # this process's hook input (one hook per process), for hook_mode's profile


def read_input() -> dict:
    global _INPUT
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}
    _INPUT = data if isinstance(data, dict) else {}
    return data


def load_config() -> dict:
    path = Path(os.environ.get("METODO_PROJECT_CONFIG") or TOOLS_ROOT / "config" / "project.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def rdd_enabled(config: dict) -> bool:
    return bool((config.get("rdd") or {}).get("enabled"))


# T8 (WU14): the activation element each non-absolute hook's mode stands for.
HOOK_ELEMENT = {"guard_gates": "push_gate", "guard_paths": "subagent_scope",
                "validate_subagent_output": "subagent_output", "reply_lint": "reply_lint"}
# The warn kinds each hook emits, so a profile OFF/LOG keeps that hook's warn silent.
WARN_KIND_HOOK = (("scope-outside", "guard_paths"), ("gate-", "guard_gates"))
_SILENT_HOOKS: set = set()


def activation_config_path() -> Path:
    """activation.json beside the project config (METODO_ACTIVATION_CONFIG overrides)."""
    explicit = os.environ.get("METODO_ACTIVATION_CONFIG")
    if explicit:
        return Path(explicit)
    project = os.environ.get("METODO_PROJECT_CONFIG")
    return (Path(project).parent if project else TOOLS_ROOT / "config") / "activation.json"


def _profile_mode(config: dict, hook: str, inp: dict) -> str | None:
    """The hook's mode from the activation profile, or None (no activation.json,
    invalid config, no receipt tier and no session floor): then today's rules."""
    element = HOOK_ELEMENT.get(hook)
    path = activation_config_path()
    if element is None or not path.is_file():
        return None
    try:
        from lib import activation
        settings = activation.load_config(path)
    except (ImportError, ValueError):
        return None
    receipt = receipt_for(current_tree(repo_root(inp)))
    tier = ((receipt or {}).get("risk") or {}).get("tier")
    sdir = session_dir(inp) if inp.get("session_id") else None
    floor = activation.session_floor(sdir) if sdir else None
    if tier not in activation.TIERS and floor is None:
        return None
    inputs = {"rdd_on": rdd_enabled(config), "tier": tier if tier in activation.TIERS else None}
    result = activation.session_profile(inputs, sdir) if sdir else activation.profile(inputs)
    # M2 (pi) stays in validate_subagent_output, which already records invalid-unenforced.
    modifiers = {"caller": "subagent" if is_subagent(inp) else "main"}
    return activation.element_mode(result["profile"], element, modifiers, settings).lower()


def hook_mode(config: dict, hook: str, inp: dict | None = None) -> str:
    """rdd.hook_modes[hook] (owner override) -> the activation profile's mode
    (off | log | warn | block) -> rdd.mode -> warn. Without activation.json
    this is exactly the pre-T8 rule. A profile OFF or LOG keeps this hook's
    visible warn silent (the ledger line still records the run)."""
    rdd = config.get("rdd") or {}
    explicit = (rdd.get("hook_modes") or {}).get(hook)
    if explicit:
        return explicit
    try:
        profiled = _profile_mode(config, hook, _INPUT if inp is None else inp)
    except Exception:  # noqa: BLE001 - a broken profile falls back to today's rule, never to OFF
        profiled = None
    if profiled is not None:
        if profiled in ("off", "log"):
            _SILENT_HOOKS.add(hook)
        return profiled
    return rdd.get("mode") or "warn"


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
    return build_files.shared_build_files(config) + list(CLAUDE_GLOBS)


def shared_build_hit(path: str, config: dict) -> str | None:
    """The shared-build or .claude pattern `path` matches, through the one
    matcher every consumer uses (lib/build_files.py)."""
    return build_files.first_match(path, shared_build_patterns(config))


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


WARN_MAX_TOKENS = 80  # context-method.md section 5; tokens = ceil(chars / 4)


def emit_warn(event: str | None, kind: str, fix: str) -> None:
    """The visible WARN channel: one `METODO-WARN <kind>: <fix>` line the agent
    reads as additionalContext. Never a permissionDecision: an `allow` would
    skip the owner's own permission prompts. Over the cap it is cut to 80
    tokens ending in an ellipsis, the same way every time. Silent when the
    activation profile set the emitting hook to OFF or LOG (hook_mode)."""
    if any(kind.startswith(prefix) and hook in _SILENT_HOOKS for prefix, hook in WARN_KIND_HOOK):
        return
    text = f"METODO-WARN {kind}: {fix}"
    limit = WARN_MAX_TOKENS * 4
    if len(text) > limit:
        text = text[:limit - 1] + "\u2026"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event or "PreToolUse", "additionalContext": text}},
                     ensure_ascii=False))


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
