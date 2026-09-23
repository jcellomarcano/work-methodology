#!/usr/bin/env bash
# Runs shape_metrics + duplication_cpd over <repo> and leaves everything in
# out/<repo_sha>/. If baselines/latest exists, it also computes the delta
# against that baseline (delta.json + delta.md) and prints it.
#
# The duplication threshold is fixed, in config/cpd.json: recalibrating it is
# a deliberate change (with its own change card), not something each run
# decides on its own. If config/cpd.json doesn't exist yet, this script fails
# hard asking for `lib/duplication_cpd.py <repo> --calibrate`.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <repo>" >&2
  exit 2
fi

REPO="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ ! -f "$TOOLS_ROOT/config/cpd.json" ]; then
  echo "ERROR: $TOOLS_ROOT/config/cpd.json doesn't exist yet." >&2
  echo "  run: python3 $TOOLS_ROOT/lib/duplication_cpd.py <repo> --calibrate" >&2
  exit 2
fi

REPO_SHA="$(git -C "$REPO" rev-parse HEAD)"
OUT_DIR="$TOOLS_ROOT/out/$REPO_SHA"
mkdir -p "$OUT_DIR"

RUN_STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "== shape_metrics: $REPO (sha $REPO_SHA) ==" >&2
python3 "$TOOLS_ROOT/lib/shape_metrics.py" "$REPO"

echo "== duplication_cpd: $REPO (sha $REPO_SHA) ==" >&2
python3 "$TOOLS_ROOT/lib/duplication_cpd.py" "$REPO"

RUN_FINISHED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "$OUT_DIR/run-meta.json" <<EOF
{
  "repo": "$REPO",
  "started_at": "$RUN_STARTED",
  "finished_at": "$RUN_FINISHED",
  "host": "$(hostname)"
}
EOF

if [ -L "$TOOLS_ROOT/baselines/latest" ]; then
  BASELINE_FILE="$TOOLS_ROOT/baselines/latest"
  echo "== delta vs $(readlink "$BASELINE_FILE") ==" >&2
  python3 -c "
import sys
sys.path.insert(0, '$TOOLS_ROOT')
from lib import baseline

before = baseline.load_json('$BASELINE_FILE')
after = baseline.load_json('$OUT_DIR/metrics.json')
result = baseline.delta(before, after)
baseline.write_json('$OUT_DIR/delta.json', result)

if result.get('verdict') == 'VOID: tool drift':
    print('ERROR: baseline and current run come from different tool_sha values (or different tool_versions).')
    print(f\"  before: {result['tool_sha_before']} {result['tool_versions_before']}\")
    print(f\"  now: {result['tool_sha_after']} {result['tool_versions_after']}\")
    print('  a delta between two versions of the tool itself is not a delta of the repo.')
    sys.exit(2)

lines = ['# delta vs baseline', '']
lines.append(f\"added: {len(result['added'])}\")
lines.append(f\"removed: {len(result['removed'])}\")
lines.append('')
lines.append('| metric | before | after | delta |')
lines.append('|---|---|---|---|')
for key in sorted(result['changed']):
    c = result['changed'][key]
    lines.append(f\"| {key} | {c['before']} | {c['after']} | {c['delta']} |\")
lines.append('')
open('$OUT_DIR/delta.md', 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
"
  cat "$OUT_DIR/delta.md" >&2
fi

echo "" >&2
echo "== metrics.md ==" >&2
cat "$OUT_DIR/metrics.md" >&2

FIXED_MIN_TOKENS=$(python3 -c "
import sys
sys.path.insert(0, '$TOOLS_ROOT')
from lib import baseline
print(baseline.load_json('$TOOLS_ROOT/config/cpd.json')['min_tokens'])
")
echo "" >&2
echo "duplication min-tokens (fixed, config/cpd.json): $FIXED_MIN_TOKENS" >&2
echo "output at: $OUT_DIR" >&2
