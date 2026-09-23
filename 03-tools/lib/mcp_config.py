#!/usr/bin/env python3
"""Writes or removes the `metodo` entry of a Claude Code .mcp.json without
touching other servers the file already declares.

Usage:
    lib/mcp_config.py <.mcp.json> [--tools-root-expr EXPR] [--repo-expr EXPR]
    lib/mcp_config.py <.mcp.json> --remove

EXPR can carry ${VAR:-default}: Claude Code expands it when starting the
server. Output: {path, changed, action}.
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


def apply(path: Path, tools_root_expr: str, repo_expr: str, do_remove: bool) -> dict:
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    merged = remove(existing) if do_remove else merge(existing, render_entry(tools_root_expr, repo_expr))
    changed = merged != (existing or {})
    if changed:
        if do_remove and not merged and path.exists():
            path.unlink()
        else:
            path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"path": str(path), "changed": changed, "action": "remove" if do_remove else "merge"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="path to the target repo's .mcp.json")
    parser.add_argument("--tools-root-expr", default=DEFAULT_TOOLS_EXPR)
    parser.add_argument("--repo-expr", default=DEFAULT_REPO_EXPR)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(apply(Path(args.path), args.tools_root_expr, args.repo_expr, args.remove), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
