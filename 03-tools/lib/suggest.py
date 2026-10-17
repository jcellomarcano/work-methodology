#!/usr/bin/env python3
"""Detects the external helpers the kit benefits from and prints the exact
command to enable what is missing (kit-init S3). It never installs anything,
never writes a file, and reads global configs only on request.

The helpers, their detect rules and their commands are data, in
config/suggestions.json (each entry names its `source` and whether the
command was `verified`). This module only interprets the rules:

  binary       the name is on PATH
  probe        argv that must exit 0 (e.g. `java -version`)
  version      argv whose output carries a version >= min
  config_flag  a dotted key of <tools>/config/project.json that must be true
  mcp_server   a server key in the repo-local MCP files; the global files
               (~/.claude.json, ~/.pi/agent/mcp.json) are opened ONLY with
               --read-global-config, read-only, to test that one key: their
               contents are never printed or stored
  status       a read-only argv whose first output line is appended to `why`

Usage:
    lib/suggest.py <repo> [--tools <tools-root>] [--runtime claude|pi|all] [--read-global-config]

Output (stdout, sorted keys): [{id, status: present|missing|unknown, why, command|null}].
`command` is null only when the helper is present; it keeps the placeholders
<repo> and <tools>. Exit 0, or 2 on usage errors.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
DATA = TOOLS_ROOT / "config" / "suggestions.json"
RUNTIMES = ("claude", "pi", "all")
TIMEOUT = 20


def load_entries(path: Path = DATA) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(json.load(fh)["suggestions"])


def _runtimes(runtime: str) -> tuple[str, ...]:
    return ("claude", "pi") if runtime == "all" else (runtime,)


def _run(argv: list[str], env: dict, cwd: Path | None) -> tuple[int, str] | None:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=TIMEOUT,
                              cwd=str(cwd) if cwd else None, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _resolve(argv: list[str], path: str, repo: Path) -> list[str] | None:
    exe = shutil.which(argv[0], path=path)
    if exe is None:
        return None
    return [exe] + [str(repo) if a == "<repo>" else a for a in argv[1:]]


def _load_json(path: Path):
    """Parsed JSON, or None if absent; raises OSError/ValueError otherwise."""
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _has_server(obj, key: str) -> bool:
    """True if any `mcpServers` object anywhere in obj holds `key` (Claude
    keeps user-scope servers at the top and local-scope ones per project)."""
    if isinstance(obj, dict):
        servers = obj.get("mcpServers")
        if isinstance(servers, dict) and key in servers:
            return True
        return any(_has_server(v, key) for v in obj.values() if isinstance(v, (dict, list)))
    if isinstance(obj, list):
        return any(_has_server(v, key) for v in obj)
    return False


def _dotted(config: dict, key: str):
    value = config
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _check_mcp(rule: dict, repo: Path, read_global: bool, home: str) -> tuple[str, str]:
    key = rule["key"]
    unreadable = []
    for rel in rule.get("repo", []):
        try:
            if _has_server(_load_json(repo / rel), key):
                return "present", ""
        except (OSError, ValueError):
            unreadable.append(rel)
    local = " or ".join(rule.get("repo", [])) or "the repo"
    if not read_global:
        return "unknown", (f"no {key} server in the repo's {local}; global configs not read "
                           f"(pass --read-global-config to check {', '.join(rule.get('global', []))})")
    for shown in rule.get("global", []):
        path = Path(home + shown[1:]) if shown.startswith("~/") else Path(shown)
        try:
            if _has_server(_load_json(path), key):
                return "present", ""
        except (OSError, ValueError):
            unreadable.append(shown)
    if unreadable:
        return "unknown", f"no {key} server found; unreadable: {', '.join(unreadable)}"
    return "missing", f"no {key} server in {local} nor in {', '.join(rule.get('global', []))}"


def evaluate(entry: dict, repo: Path, tools: Path | None, runtime: str, read_global: bool, env: dict) -> dict:
    detect, commands = entry.get("detect") or {}, entry.get("command") or {}
    path = env.get("PATH", "")
    home = env.get("HOME", "")
    reasons: list[str] = []
    unknown = False
    need_install = need_config = need_runtime = False
    why = entry["why"]

    binary = detect.get("binary")
    have_binary = binary is None or shutil.which(binary, path=path) is not None
    if not have_binary:
        reasons.append(f"{binary} is not on PATH")
        need_install = need_runtime = True

    if have_binary and detect.get("probe"):
        argv = _resolve(detect["probe"], path, repo)
        result = _run(argv, env, repo) if argv else None
        if result is None or result[0] != 0:
            reasons.append(f"`{' '.join(detect['probe'])}` failed")
            need_install = need_runtime = True

    if have_binary and detect.get("version"):
        rule = detect["version"]
        argv = _resolve(rule["argv"], path, repo)
        result = _run(argv, env, repo) if argv else None
        match = re.search(rule["regex"], result[1]) if result and result[0] == 0 else None
        minimum = tuple(rule["min"])
        if match is None:
            unknown = True
            reasons.append(f"could not read the version from `{' '.join(rule['argv'])}`")
        else:
            found = tuple(int(g) for g in match.groups())
            if found < minimum:
                reasons.append(f"{binary or rule['argv'][0]} {'.'.join(map(str, found))} is older than "
                               f"{'.'.join(map(str, minimum))}")
                need_install = need_runtime = True

    if detect.get("config_flag"):
        key = detect["config_flag"]
        config = None
        if tools is not None:
            try:
                config = _load_json(tools / "config" / "project.json")
            except (OSError, ValueError):
                config = None
        if not isinstance(config, dict):
            unknown = True
            reasons.append("<tools>/config/project.json not readable")
        elif not _dotted(config, key):
            reasons.append(f"{key} is not true in <tools>/config/project.json")
            need_config = True

    if detect.get("mcp_server"):
        state, reason = _check_mcp(detect["mcp_server"], repo, read_global, home)
        if state != "present":
            reasons.append(reason)
            need_runtime = True
            unknown = unknown or state == "unknown"

    if have_binary and not reasons and detect.get("status"):
        argv = _resolve(detect["status"], path, repo)
        result = _run(argv, env, repo) if argv else None
        line = next((l.strip() for l in (result[1] if result else "").splitlines() if l.strip()), "")
        shown = " ".join(detect["status"])
        why = f"{why}. `{shown}`: {line[:160] if line else 'no output'}"

    if not reasons:
        return {"id": entry["id"], "status": "present", "why": why, "command": None}

    parts: list[str] = []
    if need_install and commands.get("install"):
        parts.append(commands["install"])
    if need_runtime:
        if runtime == "all" and commands.get("all"):
            parts.append(commands["all"])
        else:
            parts += [commands[r] for r in _runtimes(runtime) if commands.get(r)]
    if need_config and commands.get("config"):
        parts.append(commands["config"])
    parts = list(dict.fromkeys(parts))
    missing = need_install or need_config or (need_runtime and not unknown)
    status = "missing" if missing else "unknown"
    return {"id": entry["id"], "status": status, "why": f"{why}. Detected: {'; '.join(reasons)}",
            "command": " && ".join(parts) if parts else "see config/suggestions.json"}


def suggest(repo: Path, tools: Path | None, runtime: str = "all", read_global_config: bool = False,
            env: dict | None = None, entries: list[dict] | None = None) -> list[dict]:
    env = dict(os.environ) if env is None else dict(env)
    wanted = set(_runtimes(runtime))
    out = []
    for entry in entries if entries is not None else load_entries():
        if not wanted & set(entry.get("runtimes") or ("claude", "pi")):
            continue
        out.append(evaluate(entry, Path(repo), Path(tools) if tools else None, runtime, read_global_config, env))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect the helpers the kit benefits from; print what to enable.")
    parser.add_argument("repo")
    parser.add_argument("--tools", default=None, help="tools root whose config/project.json is read")
    parser.add_argument("--runtime", choices=RUNTIMES, default="all")
    parser.add_argument("--read-global-config", action="store_true",
                        help="also test ~/.claude.json and ~/.pi/agent/mcp.json for an MCP server key (read-only)")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.repo):
        print(f"suggest: not a directory: {args.repo}", file=sys.stderr)
        return 2
    tools = Path(args.tools).expanduser() if args.tools else None
    result = suggest(Path(args.repo).expanduser().resolve(), tools, args.runtime, args.read_global_config)
    sys.stdout.write(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
