#!/usr/bin/env python3
"""Writes or removes the `metodo` entry of a Claude Code .mcp.json without
touching other servers the file already declares.

Usage:
    lib/mcp_config.py <.mcp.json> [--tools-root-expr EXPR] [--repo-expr EXPR]
    lib/mcp_config.py <.mcp.json> --remove
    lib/mcp_config.py <.pi/mcp.json> --pi-entry [--tools-root-expr EXPR] [--repo-expr EXPR]
    lib/mcp_config.py <.pi/mcp.json> --pi-override --remove

EXPR can carry ${VAR:-default}: Claude Code expands it when starting the
server. --pi-entry writes the whole server on mcpServers.metodo of
.pi/mcp.json: pi's built-in MCP never reads .mcp.json and drops, without a
word, an entry that is only an override (measured on pi 1.3.0, 2026-11-18).
`exposure: direct` is what declares the tools to the model as
mcp__metodo__<tool>; `toolPrefix: mcp` gives the same names under the
pi-mcp-adapter package. --pi-override --remove drops those kit keys (the
server keys only when they are the kit's server, then the entry, mcpServers
and the file, each only once empty); other keys stay.
Output: {path, changed, action}.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SERVER_NAME = "metodo"
DEFAULT_TOOLS_EXPR = "${METODO_TOOLS:-${HOME}/metodologia-de-trabajo/03-tools}"
DEFAULT_REPO_EXPR = "${CLAUDE_PROJECT_DIR:-}"  # empty if unset: the server falls back to cwd


def render_entry(tools_root_expr: str = DEFAULT_TOOLS_EXPR, repo_expr: str = DEFAULT_REPO_EXPR) -> dict:
    return {
        "type": "stdio",
        "command": "python3",
        "args": [f"{tools_root_expr}/mcp/server.py"],
        "env": {"METODO_TOOLS": tools_root_expr, "METODO_REPO": repo_expr},
    }


def merge(existing: dict | None, entry: dict) -> dict:
    merged = dict(existing or {})
    servers = dict(merged.get("mcpServers") or {})
    servers[SERVER_NAME] = entry
    merged["mcpServers"] = servers
    return merged


def remove(existing: dict | None) -> dict:
    merged = dict(existing or {})
    servers = dict(merged.get("mcpServers") or {})
    servers.pop(SERVER_NAME, None)
    if servers:
        merged["mcpServers"] = servers
    else:
        merged.pop("mcpServers", None)
    return merged


PI_SERVER_KEYS = ("command", "args", "exposure")
KIT_ENV_KEYS = ("METODO_TOOLS", "METODO_REPO")
FOREIGN_ACTION = "kept: mcpServers.metodo in this file is not the kit's server"


def _is_kit_server(entry: dict) -> bool:
    args = entry.get("args")
    return (entry.get("command") == "python3" and isinstance(args, list) and len(args) == 1
            and str(args[0]).endswith("/mcp/server.py"))


def _is_foreign_server(entry: object) -> bool:
    """A `metodo` entry that already declares a server which is not the kit's is the owner's."""
    return isinstance(entry, dict) and ("command" in entry or "url" in entry) and not _is_kit_server(entry)


def merge_pi_entry(existing: dict | None, tools_root_expr: str, repo_expr: str) -> dict:
    merged = dict(existing or {})
    servers = dict(merged.get("mcpServers") or {})
    current = servers.get(SERVER_NAME)
    if _is_foreign_server(current):
        return merged  # never overwritten: a later uninstall would take the owner's server with it
    entry = dict(current) if isinstance(current, dict) else {}
    rendered = render_entry(tools_root_expr, repo_expr)
    env = dict(entry["env"]) if isinstance(entry.get("env"), dict) else {}
    env.update(rendered["env"])
    entry.update({"toolPrefix": "mcp", "command": rendered["command"], "args": rendered["args"],
                  "env": env, "exposure": "direct"})
    servers[SERVER_NAME] = entry
    merged["mcpServers"] = servers
    return merged


def remove_pi_override(existing: dict | None) -> dict:
    merged = dict(existing or {})
    servers = dict(merged.get("mcpServers") or {})
    entry = servers.get(SERVER_NAME)
    if not isinstance(entry, dict):
        return merged
    entry = dict(entry)
    # A `metodo` server that is not the kit's (another command) is the owner's: untouched.
    kit_server = _is_kit_server(entry)
    if kit_server:
        for key in PI_SERVER_KEYS:
            entry.pop(key, None)
        env = entry.get("env")
        if isinstance(env, dict):  # the owner's own variables stay
            left = {k: v for k, v in env.items() if k not in KIT_ENV_KEYS}
            if left:
                entry["env"] = left
            else:
                entry.pop("env")
    if entry.get("toolPrefix") == "mcp" and (kit_server or "command" not in entry):
        entry.pop("toolPrefix")
    if entry:
        servers[SERVER_NAME] = entry
    else:
        servers.pop(SERVER_NAME)
    if servers:
        merged["mcpServers"] = servers
    else:
        merged.pop("mcpServers", None)
    return merged


def apply(path: Path, tools_root_expr: str, repo_expr: str, do_remove: bool, pi_override: bool = False,
          pi_entry: bool = False) -> dict:
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if pi_override:
        if not do_remove:
            raise ValueError("--pi-override is only supported with --remove")
        merged = remove_pi_override(existing)
    elif pi_entry:
        if do_remove:
            raise ValueError("--pi-entry writes; use --pi-override --remove to take it out")
        if _is_foreign_server(((existing or {}).get("mcpServers") or {}).get(SERVER_NAME)):
            return {"path": str(path), "changed": False, "action": FOREIGN_ACTION}
        merged = merge_pi_entry(existing, tools_root_expr, repo_expr)
    else:
        merged = remove(existing) if do_remove else merge(existing, render_entry(tools_root_expr, repo_expr))
    changed = merged != (existing or {})
    if changed:
        if do_remove and not merged and path.exists():
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"path": str(path), "changed": changed, "action": "remove" if do_remove else "merge"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="path to the target repo's .mcp.json")
    parser.add_argument("--tools-root-expr", default=DEFAULT_TOOLS_EXPR)
    parser.add_argument("--repo-expr", default=DEFAULT_REPO_EXPR)
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--pi-override", action="store_true", help="with --remove: drop the kit's keys from .pi/mcp.json")
    parser.add_argument("--pi-entry", action="store_true", help="write the whole server into .pi/mcp.json")
    args = parser.parse_args(argv)
    if args.pi_override and not args.remove:
        parser.error("--pi-override needs --remove")
    if args.pi_entry and (args.remove or args.pi_override):
        parser.error("--pi-entry writes; it takes neither --remove nor --pi-override")
    print(json.dumps(apply(Path(args.path), args.tools_root_expr, args.repo_expr, args.remove, args.pi_override,
                           args.pi_entry), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
