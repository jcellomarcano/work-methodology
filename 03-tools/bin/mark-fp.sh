#!/usr/bin/env bash
# Owner mark: ledger line <session>:<seq> was a false positive (T9, WU9).
# Thin wrapper over lib/hooks_report.py --mark-fp, which appends one line to
# out/hooks/<session>/false-positives.jsonl and never edits the ledger. The
# marks feed precision in `lib/hooks_report.py --verdicts`.
#
#   bin/mark-fp.sh <session> <seq> --reason "<why>" [--hooks-dir DIR]
#
# Exit 0 recorded, 2 usage or an unknown ledger line (nothing written).
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <session> <seq> --reason \"<why>\" [--hooks-dir DIR]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="$1"
SEQ="$2"
shift 2

exec python3 "$SCRIPT_DIR/../lib/hooks_report.py" --mark-fp "$SESSION" "$SEQ" "$@"
