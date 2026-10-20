#!/usr/bin/env bash
# Copies the benchmark scripts from their source of truth (08-benchmark/lib) into the
# harness-benchmark skill folder as top-level files, because the installer copies only the
# top-level files of a skill folder. bench_cli.py becomes bench.py. A source that does not
# exist yet is skipped with a note.
#
# usage: sync-skill.sh [--check]
#   --check  write nothing; exit 1 listing every drifted or missing copy, 0 when all match
set -euo pipefail

mode=sync
case "${1:-}" in
  "") ;;
  --check) mode=check ;;
  -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "usage: sync-skill.sh [--check]" >&2; exit 2 ;;
esac
[ $# -le 1 ] || { echo "usage: sync-skill.sh [--check]" >&2; exit 2; }

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
lib="$root/08-benchmark/lib"
skill="$root/02-skills/harness-benchmark"

# source name in lib -> copy name in the skill folder
pairs="transcript_metrics.py:transcript_metrics.py
bench_session.py:bench_session.py
bench_ab.py:bench_ab.py
bench_cli.py:bench.py"

bad=0
while IFS=: read -r src dst; do
  if [ ! -f "$lib/$src" ]; then
    echo "skip: 08-benchmark/lib/$src does not exist yet"
    continue
  fi
  if [ "$mode" = check ]; then
    if [ ! -f "$skill/$dst" ]; then
      echo "missing: 02-skills/harness-benchmark/$dst (source 08-benchmark/lib/$src)"
      bad=1
    elif ! cmp -s "$lib/$src" "$skill/$dst"; then
      echo "drift: 02-skills/harness-benchmark/$dst differs from 08-benchmark/lib/$src"
      bad=1
    fi
  else
    mkdir -p "$skill"
    cp "$lib/$src" "$skill/$dst"
    echo "synced: 02-skills/harness-benchmark/$dst"
  fi
done <<< "$pairs"

if [ "$mode" = check ] && [ "$bad" -ne 0 ]; then
  echo "run 08-benchmark/bin/sync-skill.sh to refresh the copies" >&2
  exit 1
fi
exit 0
