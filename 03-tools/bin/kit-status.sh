#!/usr/bin/env bash
# Measured status block of the kit's README (kit-init S11): every important
# change is re-measured and lands with the updated block in the same commit.
# Thin wrapper over lib/kit_status.py, which holds the measurements and the
# block contract.
#
#   bin/kit-status.sh --check                    # cheap, no suite run: is the block current?
#   bin/kit-status.sh --write [--allow-failing]  # run the suite and init on a fixture, rewrite the block
#
# --check exit 0 current, 1 stale or missing (prints the fix), 2 usage.
# --write exit 0 written, 1 refused (suite FAILED without --allow-failing,
# or the tree changed while measuring; README untouched), 2 usage.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$SCRIPT_DIR/../lib/kit_status.py" "$@"
