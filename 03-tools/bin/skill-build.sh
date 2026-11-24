#!/usr/bin/env bash
# Builds and tests the kit's skills from the declaration beside each one,
# 02-skills/<skill>/BUILD.json. Thin wrapper over lib/skill_build.py, whose
# docstring holds the BUILD.json shape and what each target checks.
#
#   bin/skill-build.sh test  [<skill>...] [--all] [--kit-plugin] [--no-cache] [--json FILE]
#   bin/skill-build.sh build [<skill>...] [--all] [--kit-plugin] [--out DIR]
#
# test   runs the declared targets (agent_skill, validate_skill_test,
#        py_type_test, py_test, eval_suite) and prints one line per target:
#        `<STATUS> <skill>:<target> <reason>`, STATUS being PASS, FAIL or SKIP.
#        A PASS is stored in out/skill-build/cache/ under a hash of the
#        target's inputs and is reported `cached` until an input changes;
#        --no-cache runs everything and stores nothing. A SKIP is not a pass.
# build  writes <out>/<skill>/<skill>-<version>.zip, the plugin package of the
#        skill (default out: out/skill-build/dist); identical inputs give
#        identical bytes.
# --kit-plugin  one more target, declared once in 02-skills/BUILD.json: the whole
#        kit as a single Claude Code plugin, every skill that has a BUILD.json
#        plus the MCP server and what it needs under tools/, with the skills'
#        tool names written as that plugin exposes them. `build` writes
#        <out>/<name>/<name>-<version>.zip (identical bytes for identical inputs)
#        and, beside it, marketplace/, a marketplace folder that lists the one
#        plugin; `test` checks the same and writes nothing. It holds no personal
#        asset, test, BUILD file, cache, out/ or vendor/ folder, and fails on a
#        tool the catalog lacks or on this machine's home path in a text file.
#
# A skill with no BUILD.json is one SKIP line. Exit: 0 no FAIL, 1 any FAIL,
# 2 a usage error (one `skill-build:` line on stderr). No network, no model.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
exec python3 -I "$TOOLS_ROOT/lib/skill_build.py" "$@"
