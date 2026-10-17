#!/usr/bin/env bash
# One command from zero to a working kit instance in a target repo: creates
# or refreshes the tools instance, adapts it, writes the audit-folder
# scaffolds, fetches the pinned tools, installs the kit for each runtime,
# saves the first baseline, draws the first map, runs the wiring doctor and
# the full-loop smoke, and suggests the helpers that are missing. Whatever
# it cannot do is printed as a pending human step naming the file to fill
# in. Thin wrapper over lib/init_kit.py, which holds the logic and the
# report contract.
#
#   bin/init.sh <repo> [--instance <dir>] [--audit <dir>] [--runtime claude|pi|all]
#               [--answers <json|file>] [--engram-project NAME] [--no-fetch]
#               [--no-baseline] [--no-smoke] [--read-global-config] [--dry-run]
#   bin/init.sh <repo> --uninstall [--instance <dir>] [--audit <dir>] [--purge]
#               [--runtime claude|pi|all] [--dry-run]
#
# Defaults: --instance ~/<repo_name>-tools, --audit ~/<repo_name>-audit,
# --runtime all. Report: <instance>/out/init/<repo_sha>.json (also on
# stdout); human summary on stderr. Never installs anything global, never
# copies personal assets, reads global configs only with
# --read-global-config. --dry-run prints the plan and writes nothing.
# Exit 0 doctor without FAIL and smoke (if run) passed, 1 otherwise, 2 usage
# or preflight.
#
# --uninstall unplugs the kit from <repo> (install.sh --uninstall: only files
# byte-identical to the kit's render go), runs doctor --absent and writes
# <instance>/out/uninstall/<repo_sha>.json (stdout only once the instance is
# gone). The instance and the audit folder stay; --purge deletes them only
# when untouched, otherwise refuses and lists why. Exit 0 kit_absent, 1 when
# something kit-owned remains (or a purge was refused), 2 usage.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <repo> [--instance <dir>] [--audit <dir>] [--runtime claude|pi|all] [--answers <json|file>]" >&2
  echo "          [--engram-project NAME] [--no-fetch] [--no-baseline] [--no-smoke] [--read-global-config] [--dry-run]" >&2
  echo "       $0 <repo> --uninstall [--instance <dir>] [--audit <dir>] [--purge] [--runtime claude|pi|all] [--dry-run]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

exec python3 "$TOOLS_ROOT/lib/init_kit.py" "$@"
