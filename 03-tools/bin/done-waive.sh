#!/usr/bin/env bash
# Owner waiver of one done-gate rule (T14, done-gate.md section 4). Thin
# wrapper over lib/done_check.py waive_main, which appends one line
# {"kind": "done-waiver", "rule", "tree_sha", "worktree_sha", "reason", "email"}
# to out/hooks/<session>/ledger.jsonl. The waiver holds only while the
# worktree fingerprint is the same; any edit ends it. The DONE-GATE block then
# shows `WAIVED by <email>: <reason>` instead of the flag.
#
#   bin/done-waive.sh DONE-xx --reason "<why>" [--session S] [--repo R] [--hooks-dir D]
#
# The owner's step, from the owner's terminal: hooks/guard_gates.py denies it
# to a subagent and asks the owner when the main session's agent runs it.
# --session defaults to the session whose ledger changed last; --repo to the
# current directory. Exit 0 written, 2 usage (nothing written).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from lib import done_check; raise SystemExit(done_check.waive_main(sys.argv[2:]))' \
  "$SCRIPT_DIR/.." "$@"
