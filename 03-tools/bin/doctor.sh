#!/usr/bin/env bash
# Wiring doctor: proves the kit is installed in <repo> and responds (agents,
# skills, MCP server, hooks, pi extension, config), with the exact fix for
# every FAIL. Thin wrapper over lib/doctor.py: writes the JSON report and
# prints a short human table.
#
#   bin/doctor.sh <repo> [--tools <tools-root>] [--runtime claude|pi|all] [--out <file>] [--absent]
#
# --out     default <tools-root>/out/doctor/<repo_sha>.json (no-sha.json when the
#           repo has no commit; <repo_sha>.absent.json with --absent). The report
#           is deterministic: sorted keys, no timestamps, no absolute paths.
# --absent  absence report after bin/install.sh <repo> --uninstall: PASS when no
#           kit agent, skill, hook, MCP entry, pi extension or override remains;
#           prints kit_absent. Exit 0 when kit_absent, 1 otherwise.
# Exit: 0 no FAIL (WARNs allowed), 1 at least one FAIL, 2 usage.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <repo> [--tools <tools-root>] [--runtime claude|pi|all] [--out <file>] [--absent]" >&2
  exit 2
fi

REPO="$1"; shift
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT=""
ABSENT=0
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --tools) [ $# -ge 2 ] || { echo "--tools needs a value" >&2; exit 2; }
             [ -d "$2" ] || { echo "tools root is not a directory: $2" >&2; exit 2; }
             TOOLS_DIR="$(cd "$2" && pwd)"; shift 2;;
    --runtime) [ $# -ge 2 ] || { echo "--runtime needs a value" >&2; exit 2; }
               ARGS+=(--runtime "$2"); shift 2;;
    --out) [ $# -ge 2 ] || { echo "--out needs a value" >&2; exit 2; }
           OUT="$2"; shift 2;;
    --absent) ABSENT=1; ARGS+=(--absent); shift;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

if [ ! -d "$REPO" ]; then
  echo "not a directory: $REPO" >&2
  exit 2
fi

if [ -z "$OUT" ]; then
  SHA="$(git -C "$REPO" rev-parse --verify --quiet HEAD 2>/dev/null || true)"
  if [ "$ABSENT" = "1" ]; then
    OUT="$TOOLS_DIR/out/doctor/${SHA:-no-sha}.absent.json"
  else
    OUT="$TOOLS_DIR/out/doctor/${SHA:-no-sha}.json"
  fi
fi

set +e
python3 "$SCRIPT_DIR/../lib/doctor.py" "$REPO" --tools "$TOOLS_DIR" --out "$OUT" --table ${ARGS[@]+"${ARGS[@]}"}
rc=$?
set -e
if [ "$rc" -le 1 ]; then
  echo "report: $OUT"
fi
exit "$rc"
