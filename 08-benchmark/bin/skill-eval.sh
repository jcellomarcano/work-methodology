#!/usr/bin/env bash
# The skill evals in one short command: list the skills that have a case, and
# plan or run the eval of one skill, several, or all of them. Thin wrapper over
# lib/skill_eval.py, which owns the command line; lib/skill_eval_run.py
# documents the plan, the scoring and the verdict.
#
#   bin/skill-eval.sh list [--root DIR]
#   bin/skill-eval.sh run <skill>... [--real] [--kit-mcp | --kit-plugin] [--tier TIER] [--runs N]
#                         [--model M] [--judge-model M] [--max-cost-usd USD] [--no-cache] [--json FILE]
#   bin/skill-eval.sh run --all [the same flags]
#   bin/skill-eval.sh validate [ROOT] [--kit DIR]
#   bin/skill-eval.sh report [--skill NAME ...] [--tier TIER] [--json FILE]
#
# list      one line per skill that has a case: `<skill>: <case> [<tier>], ...`.
# run       prints the plan of the named skills and spends nothing: per skill
#           its cases, the two arms, the runs and the cost ceiling. Only --real
#           starts `claude plugin eval`, and it prints its ceiling first (USD
#           0.50 per skill unless --max-cost-usd says otherwise). --all, or no
#           name at all, takes every skill that has a case; a skill named twice
#           counts once; `--skill NAME` is the same as naming it. Give the
#           names together, before the flags or after them: a name that
#           comes after a flag once others were given is refused (exit 2).
#           A skill whose case carries mocks/ always answers the kit's tools
#           from those files, in both arms, and starts no real server; --kit-mcp
#           and --kit-plugin start the real one only for the skills whose cases
#           carry none, so `run --all --kit-mcp` runs every skill in one
#           command. The plan says per skill which of the two it uses.
# validate  checks every case under ROOT (default: the kit's 08-benchmark/evals),
#           its mocks against the MCP catalog of the checkout --kit names.
# report    the verdict per skill from the stored results; starts nothing.
# `run --help` and `report --help` list every flag, --root, --kit and --out too.
#
# Exit: 0 done; 1 `validate` found a problem, or a real run of a skill failed;
# 2 a usage error, as one `skill-eval:` line on stderr: skills named together
# with --all, a skill that has no case (the line names it), or an evals root
# that cannot be read. No network and no model call without --real.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
exec python3 -I "$BENCH_ROOT/lib/skill_eval.py" "$@"
