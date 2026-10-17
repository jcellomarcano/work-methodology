#!/usr/bin/env bash
# Deterministic multi-agent router (odd/tasks/model-router.md R8). Thin
# wrapper over lib/router.py, which holds the decision table, the
# post-passes and the routing log.
#
#   bin/route.sh <task.json> [--as-of YYYY-MM-DD] [--log [PATH]] [--config PATH]
#
# Prints the roster as deterministic JSON. --log appends one JSON line to
# PATH (default <tools>/out/runs/routing.jsonl) and refuses a path inside
# the target repo's worktree (task.repo). offline comes from the task, else project.json `offline`, else METODO_OFFLINE=1.
# Exit 0 status ok, 1 any other status, 2 usage or refused log path.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <task.json> [--as-of YYYY-MM-DD] [--log [PATH]] [--config PATH]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$SCRIPT_DIR/../lib/router.py" "$@"
