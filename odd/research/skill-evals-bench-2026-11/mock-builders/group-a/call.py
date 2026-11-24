"""One tools/call to the kit's real MCP server over stdio; the text the model would receive goes to a file."""
import json, os, subprocess, sys
tools, repo, name, arguments, out = sys.argv[1:6]
request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": json.loads(arguments)}}
env = dict(os.environ, METODO_TOOLS=tools, METODO_REPO=repo, METODO_MEMORY="off")
proc = subprocess.run([sys.executable, os.path.join(tools, "mcp", "server.py")], input=(json.dumps(request) + "\n").encode(),
                      capture_output=True, env=env, cwd=repo)
response = json.loads(proc.stdout.decode().splitlines()[-1])
result = response["result"]
open(out, "w", encoding="utf-8").write(result["content"][0]["text"])
print(f"{name}: isError={result['isError']} bytes={len(result['content'][0]['text'].encode())}")
