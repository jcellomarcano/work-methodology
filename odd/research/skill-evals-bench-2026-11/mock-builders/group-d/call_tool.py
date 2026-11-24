#!/usr/bin/env python3
"""Call one tool of the kit's MCP server over stdio, as a client does, and print what the model receives.

Usage: call_tool.py KIT REPO TOOL ARGS_JSON [OUT_FILE]
Starts `python3 KIT/03-tools/mcp/server.py` with METODO_REPO=REPO, sends initialize and one
tools/call, and writes the text of the first content block (the answer) to OUT_FILE or stdout.
The line `isError=<bool>` goes to stderr.
"""
import json
import os
import subprocess
import sys

kit, repo, tool, args = sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4])
requests = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": args}},
]
env = dict(os.environ, METODO_REPO=repo, METODO_MEMORY="off")
env.pop("METODO_TOOLS", None)
proc = subprocess.run([sys.executable, os.path.join(kit, "03-tools", "mcp", "server.py")],
                      input="".join(json.dumps(r) + "\n" for r in requests), capture_output=True, text=True, env=env,
                      cwd=repo)
answers = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
call = next(a for a in answers if a.get("id") == 2)
if "error" in call:
    sys.exit(f"JSON-RPC error: {call['error']}")
text = call["result"]["content"][0]["text"]
print(f"isError={call['result']['isError']}", file=sys.stderr)
if len(sys.argv) > 5:
    with open(sys.argv[5], "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
else:
    print(text)
