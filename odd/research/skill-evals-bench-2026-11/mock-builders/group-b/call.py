"""Call one tool of the kit's MCP server over stdio, as a client does, and print the text it answers."""
import json
import os
import subprocess
import sys

tools_root, repo, tool, args = sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4])
env = dict(os.environ, METODO_REPO=repo, METODO_MEMORY="off")
requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": args}}]
proc = subprocess.run([sys.executable, os.path.join(tools_root, "mcp", "server.py"), "--tools-root", tools_root],
                      input="".join(json.dumps(r) + "\n" for r in requests), capture_output=True, text=True, env=env)
answer = json.loads(proc.stdout.splitlines()[-1])
if "error" in answer:
    print(json.dumps(answer["error"]))
    sys.exit(1)
sys.stdout.write(answer["result"]["content"][0]["text"] + "\n")
sys.stderr.write(f"isError={answer['result']['isError']}\n")
