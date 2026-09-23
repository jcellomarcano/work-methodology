---
name: benchmark-release
description: Compares two refs of the same repo (shape_metrics + duplication_cpd + dep_boundaries + domain_invariants) via benchmark-release.sh, with the base fixed at the last shipped release tag, never at the tip of the main branch. Use it before cutting a release, to know what really changed since the last one shipped.
version: 1.0.0
triggers:
  - release benchmark
  - compare with the last release
  - what changed since the last tag
  - benchmark-release
allowed-tools: [Read, mcp__metodo__benchmark_release, mcp__metodo__job_status]
---

**IRON LAW**: the base is the last shipped release tag, never the tip of the main branch. If `refB` is an ancestor of `refA`, the minutes say so plainly, they do not hide it.

## Input

`<repo>`, `<lastTag>` (the last shipped release tag), `<candidate>`.

## Steps

1. `mcp__metodo__benchmark_release` with `ref_a=<lastTag>`, `ref_b=<candidate>` (and `force_recompute=true` if it needs redoing); save the `run_id`.
2. `mcp__metodo__job_status` until `status: done`; read `summary` (the `out/benchmark/<a>..<b>.json` comparison) and its sibling `.md`.

## What the model may add

Prose on what improves, why, and how, backed by the change cards in the range. It never touches `not_measured` fields.

## Output

refA vs refB comparison (shape_metrics, duplication_cpd, dep_boundaries, domain_invariants) plus the what/why/how prose.

## Escalate to the owner

- `<lastTag>` does not resolve in the repo (the script does no implicit fetch, it fails dry).
- `refB` turns out to be an ancestor of `refA`.
