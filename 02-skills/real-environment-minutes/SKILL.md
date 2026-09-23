---
name: real-environment-minutes
description: Minutes for a test on a real environment (physical device, test bench, or staging) - composes benchmark-release data, the domain_invariants delta, and the change card into one document with a primary metric per arm, in median. Use it when closing a real-environment test before deciding whether a change goes to production.
version: 1.0.0
triggers:
  - real-environment minutes
  - test-bench minutes
  - close the real-environment test
  - bench report
allowed-tools: [Read, mcp__metodo__benchmark_release, mcp__metodo__job_status, mcp__metodo__domain_invariants, mcp__metodo__change_card_extract]
---

**IRON LAW**: the minutes always state whether the test used simulation/mocking and who operated the device or environment. Without that it is not minutes, it is a note.

## Input

`<repo>`, the benchmark data already computed under `out/` (or `<refA>`/`<refB>` if missing), the change card.

## Steps

1. If the data does not exist yet: `mcp__metodo__benchmark_release` with `ref_a` and `ref_b`, and `mcp__metodo__job_status` until `done`.
2. `mcp__metodo__domain_invariants` over each ref in play (in its worktree, the path the benchmark leaves), for the presence delta of the invariants declared in `config/invariants-checks.json`.
3. `mcp__metodo__change_card_extract` with the card, to bring in its context without blocking the minutes if something is missing.
4. Compose the minutes: one primary metric per arm, in median (never mean), with whether simulation/mocking was used and who operated the device or environment.

## What the model may add

Prose on what improved and why, backed by the change cards in the range. It never touches `not_measured` and never invents an arm that was not run.

## Output

Minutes with `{arm, primary_metric, median, simulation, operator, delta_domain_invariants, card}`.

## Escalate to the owner

- Simulation/mocking was active and the minutes were going to be used as evidence of a real change.
- The name of the operator who held the device or ran the environment was missing.
