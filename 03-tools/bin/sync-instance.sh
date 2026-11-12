#!/usr/bin/env bash
# Propagates the kit's code to an instance (e.g. ~/example-repo-tools): copies
# lib/ bin/ schemas/ mcp/ hooks/ tests/ file by file and recursively, so the
# instance also receives hooks/pi/ (the pi guards extension); for config/ it only adds
# what's missing (never overwrites); it doesn't touch out/, baselines/, or
# vendor/, and never deletes anything extra the instance has (its own
# modules). Committing in the instance is the owner's job, after reviewing
# the diff.
#
# The benchmark has one source of truth, the kit's 08-benchmark/: its lib/
# bin/ protocols/ land in <instance>/bench/ under the same rules (changed
# files overwritten, bytecode skipped, nothing deleted, modes kept, extras
# listed). The instance's bin/bench.sh measures with that copy.
#
# Personal assets are never copied (S8). They follow one convention, the same
# the doctor and kit_status apply: any path component named `personal`, or
# matching `*.personal.*` (both git-ignored in the kit). An instance that
# already holds one keeps it, untouched (it is never overwritten nor deleted).
#
#   bin/sync-instance.sh <instance>
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <instance>" >&2
  exit 2
fi
DST="$(cd "$1" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(cd "$SCRIPT_DIR/.." && pwd)"
BENCH_SRC="$(cd "$SRC/.." && pwd)/08-benchmark"
BENCH_DIRS=(lib bin protocols)
if [ "$DST" = "$SRC" ]; then
  echo "the instance is the kit itself" >&2
  exit 2
fi

# The personal-asset convention, relative to 03-tools/: never synced.
PERSONAL_RULE="any path with a component named personal/ or matching *.personal.*"
is_personal() {
  # '.personal.' holds no slash, so a match always lies inside one component.
  case "/$1/" in
    */personal/*|*.personal.*) return 0;;
  esac
  return 1
}

copied=0; same=0
# copy_tree <src-dir> <dst-dir> <rel-prefix>: file by file, recursive; prints
# paths relative to the instance (<rel-prefix>/<path inside the dir>).
copy_tree() {
  local from="$1" to="$2" prefix="$3" f inner rel
  [ -d "$from" ] || return 0
  while IFS= read -r -d '' f; do
    inner="${f#"$from/"}"
    rel="$prefix/$inner"
    case "$rel" in *__pycache__*|*.pyc) continue;; esac
    is_personal "$rel" && continue
    mkdir -p "$(dirname "$to/$inner")"
    if [ -f "$to/$inner" ] && cmp -s "$f" "$to/$inner"; then
      same=$((same + 1))
    else
      if [ -f "$to/$inner" ]; then echo "  ~ $rel"; else echo "  + $rel"; fi
      cp -p "$f" "$to/$inner"
      copied=$((copied + 1))
    fi
  done < <(find "$from" -type f -print0)
}
for dir in lib bin schemas mcp hooks tests; do
  copy_tree "$SRC/$dir" "$DST/$dir" "$dir"
done
for dir in "${BENCH_DIRS[@]}"; do
  copy_tree "$BENCH_SRC/$dir" "$DST/bench/$dir" "bench/$dir"
done

# config/: only what's missing, never overwrites what the instance already decided
added_cfg=0
while IFS= read -r -d '' f; do
  rel="${f#"$SRC/"}"
  is_personal "$rel" && continue
  if [ ! -e "$DST/$rel" ]; then
    mkdir -p "$DST/$(dirname "$rel")"
    cp -p "$f" "$DST/$rel"
    echo "  + $rel (missing config; check whether your domain's example fits better)"
    added_cfg=$((added_cfg + 1))
  fi
done < <(find "$SRC/config" -type f -print0)

echo
echo "only in the instance (kept as is):"
for dir in lib bin schemas mcp hooks tests; do
  [ -d "$DST/$dir" ] || continue
  while IFS= read -r -d '' f; do
    rel="${f#"$DST/"}"
    case "$rel" in *__pycache__*|*.pyc) continue;; esac
    [ -f "$SRC/$rel" ] || echo "  $rel"
  done < <(find "$DST/$dir" -type f -print0)
done
for dir in "${BENCH_DIRS[@]}"; do
  [ -d "$DST/bench/$dir" ] || continue
  while IFS= read -r -d '' f; do
    rel="${f#"$DST/bench/"}"
    case "$rel" in *__pycache__*|*.pyc) continue;; esac
    [ -f "$BENCH_SRC/$rel" ] || echo "  bench/$rel"
  done < <(find "$DST/bench/$dir" -type f -print0)
done

echo
echo "personal, never synced: $PERSONAL_RULE"

echo
echo "summary: $copied copied/updated, $same unchanged, $added_cfg config files added. Next: (cd $DST && python3 -m unittest discover tests) and review git diff before committing."
