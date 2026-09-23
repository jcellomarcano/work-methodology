#!/usr/bin/env bash
# Propagates the kit's code to an instance (e.g. ~/example-repo-tools): copies
# lib/ bin/ schemas/ mcp/ hooks/ tests/ file by file and recursively, so the
# instance also receives hooks/pi/ (the pi guards extension); for config/ it only adds
# what's missing (never overwrites); it doesn't touch out/, baselines/, or
# vendor/, and never deletes anything extra the instance has (its own
# modules). Committing in the instance is the owner's job, after reviewing
# the diff.
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
if [ "$DST" = "$SRC" ]; then
  echo "the instance is the kit itself" >&2
  exit 2
fi

copied=0; same=0
for dir in lib bin schemas mcp hooks tests; do
  [ -d "$SRC/$dir" ] || continue
  while IFS= read -r -d '' f; do
    rel="${f#"$SRC/"}"
    case "$rel" in *__pycache__*|*.pyc) continue;; esac
    mkdir -p "$DST/$(dirname "$rel")"
    if [ -f "$DST/$rel" ] && cmp -s "$f" "$DST/$rel"; then
      same=$((same + 1))
    else
      if [ -f "$DST/$rel" ]; then echo "  ~ $rel"; else echo "  + $rel"; fi
      cp -p "$f" "$DST/$rel"
      copied=$((copied + 1))
    fi
  done < <(find "$SRC/$dir" -type f -print0)
done

# config/: only what's missing, never overwrites what the instance already decided
added_cfg=0
while IFS= read -r -d '' f; do
  rel="${f#"$SRC/"}"
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

echo
echo "summary: $copied copied/updated, $same unchanged, $added_cfg config files added. Next: (cd $DST && python3 -m unittest discover tests) and review git diff before committing."
