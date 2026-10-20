#!/usr/bin/env bash
# Run a check and record it in runs.jsonl, the done gate's green proof
# (context-method §6). Thin wrapper over lib/run_check.py.
#
#   bin/run-check.sh <name> [--runs-dir DIR] [--cwd DIR] -- <command...>
#
# The command's exit code passes through unchanged; exit 2 on a usage error
# before anything runs. One line per run goes to <tools>/out/runs/runs.jsonl
# (or $METODO_RUNS_DIR), the combined output to <runs>/<seq>.log; a runs dir
# on a path of the target repo that git does not ignore is refused.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$SCRIPT_DIR/../lib/run_check.py" "$@"
