#!/usr/bin/env bash
# Installs the kit into a repo for whichever runtimes you name. The kit has
# one source of truth (01-roles/agents/, 02-skills/, 03-tools/lib/,
# 03-tools/mcp/server.py); this script only picks the adapters that render it.
#
#   bin/install.sh <repo> [--runtime claude|pi|all] [--tools <dir>]
#                         [--engram-project NAME]
#
# --runtime           default all. claude delegates to install-claude.sh, pi to
#                     install-pi.sh; all runs both, in that order.
# --tools <dir>       tools root the hooks, the extension and the server will
#                     use in that repo; defaults to this kit. Passed through.
# --engram-project N  writes memory.engram_project in the tools instance's
#                     config/project.json. Without it, nothing is written and
#                     engram_bridge falls back to ENGRAM_PROJECT and then to
#                     the repo folder's name.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <repo> [--runtime claude|pi|all] [--tools <dir>] [--engram-project NAME]" >&2
  exit 2
fi

REPO="$(cd "$1" && pwd)"; shift
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TOOLS_DIR="$TOOLS_ROOT"
RUNTIME="all"
ENGRAM_PROJECT=""
PASSTHROUGH=()

while [ $# -gt 0 ]; do
  case "$1" in
    --runtime) RUNTIME="$2"; shift 2;;
    --tools) TOOLS_DIR="$(cd "$2" && pwd)"; PASSTHROUGH+=(--tools "$TOOLS_DIR"); shift 2;;
    --engram-project) ENGRAM_PROJECT="$2"; shift 2;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

case "$RUNTIME" in
  claude|pi|all) ;;
  *) echo "unknown runtime: $RUNTIME (claude, pi, all)" >&2; exit 2;;
esac

if [ -n "$ENGRAM_PROJECT" ]; then
  echo "== engram project -> $TOOLS_DIR/config/project.json =="
  python3 - "$TOOLS_DIR/config/project.json" "$ENGRAM_PROJECT" <<'PY'
import json, sys
from pathlib import Path
path, name = Path(sys.argv[1]), sys.argv[2]
data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
memory = dict(data.get("memory") or {})
before = dict(memory)
memory.setdefault("enabled", True)
memory["engram_project"] = name
data["memory"] = memory
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"  = memory.engram_project already {name}" if before == memory else f"  + memory.engram_project = {name}")
PY
fi

if [ "$RUNTIME" = "claude" ] || [ "$RUNTIME" = "all" ]; then
  echo
  echo "############ claude code ############"
  bash "$SCRIPT_DIR/install-claude.sh" "$REPO" ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
fi

if [ "$RUNTIME" = "pi" ] || [ "$RUNTIME" = "all" ]; then
  echo
  echo "############ pi ############"
  bash "$SCRIPT_DIR/install-pi.sh" "$REPO" ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
fi
