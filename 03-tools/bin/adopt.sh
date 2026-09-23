#!/usr/bin/env bash
# Adapts this shared kit (03-tools/) to ONE specific project: writes
# config/project.json with docs_root pointing at the given <audit-folder>, and
# leaves the domain-dependent config/ files (dep-boundaries.json,
# invariants-checks.json, duplication-targets.json, property-hierarchy-map.json)
# at their generic minimal placeholder unless they already exist (idempotent:
# never overwrites a config already adapted by hand). If the project's domain
# looks like a critical-flow domain (several payment providers behind a common
# interface), copy the 4 full examples from config/examples/critical-flow/ instead,
# with --critical-flow-example.
#
# Usage:
#   bin/adopt.sh <repo> <audit-folder> [--critical-flow-example]
#
# <audit-folder> is the path (absolute or under $HOME) where the project's
# documentation lives (change cards already written, invariants, methodology,
# agent protocol...). docs_lint.py and the rest of the skills read it from
# there.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <repo> <audit-folder> [--critical-flow-example]" >&2
  exit 2
fi

REPO="$(cd "$1" && pwd)"
AUDIT_FOLDER_RAW="$2"
USE_CRITICAL_FLOW_EXAMPLE=0
if [ "${3:-}" = "--critical-flow-example" ]; then
  USE_CRITICAL_FLOW_EXAMPLE=1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_DIR="$TOOLS_ROOT/config"
EXAMPLES_DIR="$CONFIG_DIR/examples/critical-flow"

# docs_root is stored exactly as given (typically "~/something"): the
# config/project.json reader expands "~" at run time, not here.
AUDIT_FOLDER="$AUDIT_FOLDER_RAW"

echo "== config/project.json =="
python3 - "$CONFIG_DIR/project.json" "$AUDIT_FOLDER" <<'PYEOF'
import json
import sys
from pathlib import Path

config_path, docs_root = Path(sys.argv[1]), sys.argv[2]
if config_path.exists():
    config = json.loads(config_path.read_text(encoding="utf-8"))
else:
    config = {}

config.setdefault("_comment", "The only file a new project has to fill in to adapt the kit.")
config["docs_root"] = docs_root
config.setdefault("shared_build_files", [
    "settings.gradle", "build.gradle", "gradle.properties",
    "gradle/libs.versions.toml", "app/build.gradle",
])
config.setdefault("money_paths", ["payment/", "framework/payment/", "ui/gatewaypay/"])
config.setdefault("property_order", [
    "Data integrity", "State correctness", "Identity/uniqueness", "Auditability",
    "Recoverability", "Security", "Performance", "UX",
])
config.setdefault("invariant_prefix", "INV")
config.setdefault("extra_invariant_tokens", ["ARCH-006"])
config.setdefault("language", "kotlin")
config.setdefault("ticket_keys", ["DEV", "POS"])

config_path.write_text(json.dumps(config, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"  docs_root -> {docs_root}")
PYEOF

if [ "$USE_CRITICAL_FLOW_EXAMPLE" -eq 1 ]; then
  echo "== copying examples/critical-flow to config/ (critical-flow domain) =="
  for name in dep-boundaries.json invariants-checks.json duplication-targets.json property-hierarchy-map.json; do
    src="$EXAMPLES_DIR/$name"
    dst="$CONFIG_DIR/$name"
    if [ -f "$dst" ] && ! cmp -s "$src" "$dst"; then
      echo "  ~ $dst (overwritten with the critical-flow example: check the diff if you had already touched it)"
    else
      echo "  + $dst"
    fi
    cp "$src" "$dst"
  done
else
  echo "== config/dep-boundaries.json, invariants-checks.json, duplication-targets.json, property-hierarchy-map.json =="
  echo "  stay at their generic minimal placeholder (or as they already were); use --critical-flow-example to start from the critical-flow examples"
fi

echo
echo "== next: install the agents/skills in the repo =="
echo "  bin/install-claude.sh $REPO"
echo
echo "== adaptation checklist =="
CHECKLIST="$TOOLS_ROOT/../05-adopt/checklist.md"
if [ -f "$CHECKLIST" ]; then
  cat "$CHECKLIST"
else
  cat <<'CHECKEOF'
  1) review config/project.json: money_paths, property_order, invariant_prefix, language
  2) review config/dep-boundaries.json against the repo's real modules (nodes, prefixes)
  3) review config/invariants-checks.json: delete the example, declare your own invariants
  4) review config/property-hierarchy-map.json and config/style-guide-map.json (project rule ids)
  5) run: bin/install-claude.sh <repo>
  6) run: python3 lib/duplication_cpd.py <repo> --calibrate   (sets config/cpd.json)
  7) run: bin/metrics.sh <repo>   (first baseline: bin/metrics.sh saves it with --save)
CHECKEOF
fi
