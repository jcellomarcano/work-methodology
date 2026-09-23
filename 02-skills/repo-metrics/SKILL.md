---
name: repo-metrics
description: Repo shape delta (shape_metrics + duplication_cpd) against the latest baseline, via metrics.sh. Use it to see whether a change bloated files/functions or raised duplication before merging.
version: 1.0.0
triggers:
  - repo metrics
  - shape metrics delta
  - duplication went up
  - compare with the baseline
allowed-tools: [Read, mcp__metodo__metrics_delta, mcp__metodo__job_status]
---

**IRON LAW**: if the tools changed between the baseline and this run (drift), the delta is not reported as a number, it is reported as VOID.

## Input

`<repo>`.

## Steps

1. `mcp__metodo__metrics_delta` on `<repo>`; save the `run_id`.
2. `mcp__metodo__job_status` until `status: done`: `summary` is `delta.json` if `baselines/latest` existed, otherwise `metrics.json`. An `exit_code` of 2 is tool drift and the delta is reported VOID.

## What the model may add

Interpreting which module explains the bulk of the delta. It never recalculates a number the script already gave.

## Output

`delta.md` exactly as the script writes it; if there is tool drift between baseline and run, it is declared VOID, not "no changes".

## Escalate to the owner

- `config/cpd.json` does not exist yet (the script asks for `lib/duplication_cpd.py <repo> --calibrate` run by hand).
- The duplication delta crosses the fixed threshold in `config/cpd.json`.
