#!/usr/bin/env bash
# Union of what shape_metrics + duplication_cpd + dep_boundaries already
# detect: files over 500 lines, long functions (file-level: see the
# docstring in lib/clean_pass.py), var/lateinit hotspots, duplication
# clusters, and boundary violations. Only flags rows with their rule; it
# proposes nothing: that's the skill's job.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <repo>" >&2
  exit 2
fi

REPO="$(cd "$1" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "== shape_metrics: $REPO ==" >&2
python3 "$TOOLS_ROOT/lib/shape_metrics.py" "$REPO"

echo "== duplication_cpd: $REPO ==" >&2
python3 "$TOOLS_ROOT/lib/duplication_cpd.py" "$REPO"

echo "== dep_boundaries: $REPO ==" >&2
python3 "$TOOLS_ROOT/lib/dep_boundaries.py" "$REPO"

echo "== assembling clean-pass.json ==" >&2
python3 "$TOOLS_ROOT/lib/clean_pass.py" "$REPO"

REPO_SHA="$(git -C "$REPO" rev-parse HEAD)"
OUT_DIR="$TOOLS_ROOT/out/$REPO_SHA"
echo "" >&2
cat "$OUT_DIR/clean-pass.md" >&2
echo "output at: $OUT_DIR" >&2
