#!/usr/bin/env python3
"""The `metodo` MCP server over stdio (JSON-RPC 2.0, one object per line):
exposes the kit's deterministic scripts as typed tools, so an agent can call
them as a function instead of composing bash commands with paths and flags.
Only the protocol's tools subset: initialize, notifications/initialized,
ping, tools/list, tools/call. All logging goes to stderr; stdout is
exclusively the JSON-RPC channel.

Usage:
    python3 mcp/server.py            # as a server, started by Claude Code
    python3 mcp/server.py --selftest # initialize + tools/list in-process; exit 1 on any failure
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path

TOOLS_ROOT = Path(__file__).resolve().parent.parent
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from lib import baseline  # noqa: E402
from mcp import catalog, registry  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "metodo"
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = -32700, -32600, -32601, -32602, -32603

log = logging.getLogger("metodo.mcp")


def server_version() -> str:
    try:
        return baseline.git_head_sha(TOOLS_ROOT)[:12]
    except Exception:  # noqa: BLE001 - a kit without git does not block serving
        return "unknown"


def tools_list() -> dict:
    return {"tools": [{"name": t.name, "description": t.description, "inputSchema": t.input_schema} for t in catalog.TOOLS]}


def _result(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(msg: dict, ctx: registry.Ctx) -> dict | None:
    """Returns the response, or None for notifications (no id)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return _error(msg.get("id") if isinstance(msg, dict) else None, INVALID_REQUEST, "invalid request")
    method = msg["method"]
    params = msg.get("params") or {}
    msg_id = msg.get("id")
    is_notification = "id" not in msg

    if method == "initialize":
        client_version = params.get("protocolVersion")
        if client_version and client_version != PROTOCOL_VERSION:
            log.warning("client protocolVersion %s, server pins %s", client_version, PROTOCOL_VERSION)
        return _result(msg_id, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                                "serverInfo": {"name": SERVER_NAME, "version": server_version()}})
    if method == "notifications/initialized" or method.startswith("notifications/"):
        return None
    if is_notification:
        return None
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, tools_list())
    if method == "tools/call":
        name = params.get("name")
        spec = catalog.BY_NAME.get(name)
        if spec is None:
            return _error(msg_id, INVALID_PARAMS, f"unknown tool: {name}")
        arguments = params.get("arguments") or {}
        try:
            return _result(msg_id, registry.run(spec, arguments, ctx))
        except registry.InvalidParams as exc:
            return _error(msg_id, INVALID_PARAMS, f"{name}: {exc}")
    return _error(msg_id, METHOD_NOT_FOUND, f"method not found: {method}")


def serve(ctx: registry.Ctx, stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout
    for raw in stdin:
        line = raw.decode("utf-8", errors="replace").strip() if isinstance(raw, bytes) else raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            response = _error(None, PARSE_ERROR, "parse error")
        else:
            try:
                response = handle(msg, ctx)
            except Exception as exc:  # noqa: BLE001 - never bring down the server over one call
                log.error("internal error: %s\n%s", exc, traceback.format_exc())
                response = _error(msg.get("id") if isinstance(msg, dict) else None, INTERNAL_ERROR, "internal error")
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0


def selftest(ctx: registry.Ctx) -> int:
    init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": PROTOCOL_VERSION}}, ctx)
    listed = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, ctx)
    tools = listed["result"]["tools"]
    names = [t["name"] for t in tools]
    problems = []
    if len(names) != len(set(names)):
        problems.append("duplicate tool names")
    for tool in tools:
        schema = tool["inputSchema"]
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            problems.append(f"{tool['name']}: inputSchema must be a closed object")
        if not set(schema.get("required", [])) <= set(schema.get("properties", {})):
            problems.append(f"{tool['name']}: required not in properties")
    print(json.dumps({"server": init["result"]["serverInfo"], "protocolVersion": PROTOCOL_VERSION, "tools": len(names),
                      "repo": str(ctx.repo) if ctx.repo else None, "problems": problems}, indent=2))
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--tools-root", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    ctx = registry.default_ctx(Path(args.tools_root) if args.tools_root else None)
    if args.selftest:
        return selftest(ctx)
    log.info("metodo mcp server up: tools_root=%s repo=%s", ctx.tools_root, ctx.repo)
    return serve(ctx)


if __name__ == "__main__":
    raise SystemExit(main())
