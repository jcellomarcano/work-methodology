---
name: verify-per-commit
description: Runs the verify.sh battery (or --full) commit by commit over a range, each one in a disposable worktree, via verify-commit.sh. Use it when you want to know at which exact commit on a branch something broke, not just whether the tip passes.
version: 1.0.0
triggers:
  - verify commit by commit
  - which commit broke it
  - verify-commit
  - per-commit battery
allowed-tools: [Read, mcp__metodo__verify_commit, mcp__metodo__job_status]
---

**IRON LAW**: one build at a time. Two runs of this (or this and `benchmark-release`) never build the same repo at once.

## Input

`<repo>`, `<range>` (`git log A..B` semantics: excludes A, includes through B), `--full` optional.

## Steps

1. `mcp__metodo__verify_commit` with `range` (and `full=true` if it applies); save the `run_id` it returns.
2. `mcp__metodo__job_status` with `wait_seconds=120` until `status: done`; read `summary.commits[]` commit by commit. An `exit_code` of 2 is an empty range or a usage error, not a FAIL of the battery.

## What the model may add

Pointing out which commit is suspected of introducing the failure when the pattern gives it away (the first one that fails after a run of PASSes). It never reinterprets a PASS as FAIL or the other way around.

## Output

Commit -> verdict table, exactly as the script prints it.

## Escalate to the owner

- The range is large (the script already warns: it runs the battery once per commit, several minutes each with `--full`).
- The failure shows up on a commit that touches no code (suspect the environment, not the change).
