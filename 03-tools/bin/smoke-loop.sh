#!/usr/bin/env bash
# Full-loop smoke: change card -> receipt start -> captures -> finalize on a
# throwaway local clone of <repo>; the user's repo is only read. Thin wrapper
# over lib/smoke_loop.py, which holds the logic and the report contract.
#
#   bin/smoke-loop.sh <repo> [--tools <tools-root>] [--keep] [--out <file>]
#
# Report: <tools-root>/out/smoke/<repo_sha>.json unless --out. Instance
# config: METODO_PROJECT_CONFIG, else <tools-root>/config/project.json.
# Exit 0 PASS, 1 FAIL, 2 usage.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <repo> [--tools <tools-root>] [--keep] [--out <file>]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

exec python3 "$TOOLS_ROOT/lib/smoke_loop.py" "$@"
