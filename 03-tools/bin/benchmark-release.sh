#!/usr/bin/env bash
# Compares <refA> and <refB> of the same repo: for each sha missing
# out/<sha>/metrics.json (or when --force-recompute is passed) it creates a
# disposable worktree, runs shape_metrics + duplication_cpd (fixed threshold
# from config/cpd.json) + dep_boundaries + domain_invariants against it, and
# removes it. Serialized with out/.gradle.lock (lib/worktree.sh): none of
# this invokes Gradle, but it's the same serialization verify-commit.sh uses
# over worktrees of the same repo, in case they run at the same time.
#
# Never resolves refs with an implicit fetch: if <refA>/<refB> don't exist
# in the repo as it stands, this fails hard asking for them to be fetched
# by hand first.
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "usage: $0 <repo> <refA> <refB> [--force-recompute]" >&2
  exit 2
fi

REPO="$(cd "$1" && pwd)"
REF_A="$2"
REF_B="$3"
FORCE_FLAG="${4:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/worktree.sh
source "$TOOLS_ROOT/lib/worktree.sh"

if [ ! -f "$TOOLS_ROOT/config/cpd.json" ]; then
  echo "ERROR: $TOOLS_ROOT/config/cpd.json doesn't exist yet." >&2
  echo "  run: python3 $TOOLS_ROOT/lib/duplication_cpd.py <repo> --calibrate" >&2
  exit 2
fi

resolve_sha() {
  local ref="$1"
  if ! git -C "$REPO" rev-parse --verify "${ref}^{commit}" 2>/dev/null; then
    echo "ERROR: ref '$ref' doesn't resolve in $REPO (never fetched automatically; fetch it by hand first)" >&2
    exit 2
  fi
}

SHA_A="$(resolve_sha "$REF_A")"
SHA_B="$(resolve_sha "$REF_B")"
echo "== $REF_A -> $SHA_A ==" >&2
echo "== $REF_B -> $SHA_B ==" >&2

LOCK_DIR="$TOOLS_ROOT/out/.gradle.lock"
WORKTREES_DIR="$TOOLS_ROOT/out/worktrees"
mkdir -p "$WORKTREES_DIR"

analyze_sha() {
  local sha="$1"
  local out_dir="$TOOLS_ROOT/out/$sha"

  if [ -f "$out_dir/metrics.json" ] && [ "$FORCE_FLAG" != "--force-recompute" ]; then
    echo "-- $sha: already computed (use --force-recompute to redo it) --" >&2
    return 0
  fi

  local worktree_dir="$WORKTREES_DIR/benchmark-$sha"
  worktree_lock_acquire "$LOCK_DIR"
  worktree_add "$REPO" "$sha" "$worktree_dir"

  echo "-- $sha: shape_metrics --" >&2
  python3 "$TOOLS_ROOT/lib/shape_metrics.py" "$worktree_dir"
  echo "-- $sha: duplication_cpd --" >&2
  python3 "$TOOLS_ROOT/lib/duplication_cpd.py" "$worktree_dir"
  echo "-- $sha: dep_boundaries --" >&2
  python3 "$TOOLS_ROOT/lib/dep_boundaries.py" "$worktree_dir"
  echo "-- $sha: domain_invariants --" >&2
  python3 "$TOOLS_ROOT/lib/domain_invariants.py" "$worktree_dir"

  worktree_remove "$REPO" "$worktree_dir"
  worktree_lock_release "$LOCK_DIR"
}

analyze_sha "$SHA_A"
analyze_sha "$SHA_B"

echo "== assembling benchmark $REF_A..$REF_B ==" >&2
python3 "$TOOLS_ROOT/lib/benchmark_release.py" "$REPO" "$REF_A" "$REF_B"
