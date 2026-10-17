#!/usr/bin/env bash
# Snapshot of the repo as it stands: shape_metrics + dep_boundaries +
# hotspots (most-touched files in the last 90 days) + a simulated merge of
# the current branch against the base ref (only to see which files would
# collide: it never does a real merge, nor touches the repo).
#
#   bin/cartography.sh <repo> [--target-branch REF]
#
# The base ref comes from lib/base_ref.py: --target-branch, then the active
# config's test_sectors.base_ref (METODO_PROJECT_CONFIG or this tools root's
# config/project.json), then origin/HEAD, then origin/develop.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <repo> [--target-branch REF]" >&2
  exit 2
fi

REPO="$(cd "$1" && pwd)"; shift
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EXPLICIT_TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target-branch) EXPLICIT_TARGET="${2:?--target-branch needs a ref}"; shift 2;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
if [ -n "$EXPLICIT_TARGET" ]; then
  TARGET_BRANCH="$(python3 "$TOOLS_ROOT/lib/base_ref.py" "$REPO" --base "$EXPLICIT_TARGET")"
else
  TARGET_BRANCH="$(python3 "$TOOLS_ROOT/lib/base_ref.py" "$REPO")"
fi

echo "== shape_metrics: $REPO ==" >&2
python3 "$TOOLS_ROOT/lib/shape_metrics.py" "$REPO"

echo "== dep_boundaries: $REPO ==" >&2
python3 "$TOOLS_ROOT/lib/dep_boundaries.py" "$REPO"

echo "== hotspots (90 days) ==" >&2
HOTSPOTS_FILE="$(mktemp)"
CONFLICTS_FILE="$(mktemp)"
trap 'rm -f "$HOTSPOTS_FILE" "$CONFLICTS_FILE"' EXIT

git -C "$REPO" log --since=90.days --format= --name-only -- . 2>/dev/null \
  | grep -v '^$' \
  | grep -v '^\.claude/' \
  | sort | uniq -c > "$HOTSPOTS_FILE"

echo "== merge-tree vs $TARGET_BRANCH ==" >&2
MERGE_TREE_UNAVAILABLE_FLAG=""
if git -C "$REPO" rev-parse --verify "$TARGET_BRANCH" >/dev/null 2>&1; then
  # git >= 2.38 has --write-tree (does a real, non-trivial merge, and marks
  # conflicts with "CONFLICT (...): ... in <path>" lines); before that only
  # the classic 3-argument form exists (base, ours, theirs), which prints a
  # diff3 with "  our/their/base <mode> <oid> <path>" headers for each
  # colliding file, with no distinct exit code for "there was a conflict".
  if git merge-tree -h 2>&1 | grep -q -- '--write-tree'; then
    git -C "$REPO" merge-tree --write-tree HEAD "$TARGET_BRANCH" 2>&1 \
      | grep -oE 'CONFLICT \([^)]*\): .* in .+' \
      | sed -E 's/.* in //' \
      | sort -u > "$CONFLICTS_FILE" || true
  else
    BASE_SHA="$(git -C "$REPO" merge-base HEAD "$TARGET_BRANCH")"
    git -C "$REPO" merge-tree "$BASE_SHA" HEAD "$TARGET_BRANCH" 2>&1 \
      | grep -E '^\s+(base|our|their)\s' \
      | awk '{print $NF}' \
      | sort -u > "$CONFLICTS_FILE" || true
  fi
else
  echo "WARNING: $TARGET_BRANCH doesn't exist in this checkout; skipping the merge simulation" >&2
  MERGE_TREE_UNAVAILABLE_FLAG="--merge-tree-unavailable"
fi

echo "== assembling cartography.json ==" >&2
# shellcheck disable=SC2086
python3 "$TOOLS_ROOT/lib/cartography.py" "$REPO" \
  --hotspots-file "$HOTSPOTS_FILE" \
  --conflicts-file "$CONFLICTS_FILE" \
  --target-branch "$TARGET_BRANCH" \
  $MERGE_TREE_UNAVAILABLE_FLAG

REPO_SHA="$(git -C "$REPO" rev-parse HEAD)"
OUT_DIR="$TOOLS_ROOT/out/$REPO_SHA"
echo "" >&2
cat "$OUT_DIR/cartography.md" >&2
echo "output at: $OUT_DIR" >&2
