#!/usr/bin/env bash
# The benchmark inside an instance: measures every Claude Code session of
# <repo> and writes the phase 1 report, all under <instance>/out/bench/. Thin
# wrapper over lib/bench_collect.py.
#
#   bin/bench.sh collect <repo> [--tools <instance>]   measure new or changed sessions
#   bin/bench.sh report  <repo> [--tools <instance>]   collect, git + kit extracts, phase 1 report
#   bin/bench.sh status  <repo> [--tools <instance>]   what is measured, without measuring
#   bin/bench.sh adopt   <repo> [--tools <instance>]   record the install timestamp once
#   bin/bench.sh ab <repo> <run|judge|report> [args] [--tools <instance>]
#                                                      the A/B experiment: forwards to
#                                                      <instance>/bench/lib/bench_cli.py as
#                                                      ab, judge and report with [args]
#
# The instance is --tools, else $METODO_TOOLS, else this script's parent dir.
# Transcripts come from ${CLAUDE_PROJECTS_DIR:-~/.claude/projects}. Exit: 0 ok
# (collect also when single sessions failed: they are counted), 1 report
# failed, 2 usage or no bench/lib in the instance; ab exits with the code of
# the forwarded command.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
exec python3 "$TOOLS_ROOT/lib/bench_collect.py" "$@"
