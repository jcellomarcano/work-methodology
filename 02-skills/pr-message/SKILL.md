---
name: pr-message
description: PR message with the change_card_validator gate (and, for release PRs, benchmark-release) already embedded. Use it when opening the PR for a change with a card, or the PR for a release.
version: 1.1.0
triggers:
  - pr message
  - open the pr
  - pr template
  - release pr
allowed-tools: [Read, Agent, mcp__metodo__change_card_validate, mcp__metodo__benchmark_release, mcp__metodo__job_status, mcp__metodo__receipt_status, mcp__metodo__done_check]
---

**IRON LAW**: every skipped check (`--no-verify` or equivalent) goes in "What was NOT tested", never kept quiet.

## Input

`<repo>`, the change card, and for release PRs: `<lastTag>` and `<candidate>`.

## Steps

1. `mcp__metodo__change_card_validate` with `card_path`; a FAIL blocks the message.
2. If it is a release PR: `mcp__metodo__benchmark_release` with `ref_a=<lastTag>` and `ref_b=<candidate>`, and `mcp__metodo__job_status` until `done`.
3. `mcp__metodo__receipt_status` on the repo: copy as-is into "What was NOT tested" whatever the receipt says was missing (`verdict_reasons`, missing captures, `skipped_no_credential` from `verify_sectors`, any `owner_ack` of delivery without a receipt) and any `--no-verify`; never summarize it.
4. Write the final reply that hands over the PR to a file and run `mcp__metodo__done_check` on it (`reply_path`, `repo`, `session_dir` when known); paste its `flag_block` verbatim in that reply and copy every FLAG, BLOCK or WAIVED line into "What was NOT tested" (COM-20).
5. **Before and after**: one row per observable effect the change touches (behavior, output, metric, file or doc state), as `| Observable | Before (<base ref>) | After (<head>) | Evidence |`. Both sides come from the same command, test or script run at each ref; a side that was not measured says `not measured` and the gap goes into "What was NOT tested". For a release PR, the benchmark numbers fill the metric rows.
6. Draft the body in this order: **What and why** (in customer-facing language if it is a release PR), then **Before and after**, then a `<!-- -->` block with the card, the receipt's verdict, and the Benchmark section, then **What was NOT tested**.

## Checklist

Comments: every new comment says a why the code cannot (DOC-001); every new KDoc opens with a summary
fragment and carries no tag the signature already says (DOC-002); every action tag is `TODO(KEY-###):`
with `KEY` among the project keys in `config/project.json:ticket_keys` (for example `DEV`), and no
`NEEDS-COMMENT` remains (DOC-003).

PRs on the kit itself: README status block current (`03-tools/bin/kit-status.sh --check` exit 0); a
stale block means the change was not re-measured (run `--write` and commit the README with it).

## What the model may add

The "What and why" prose and the "Observable" names. Never the benchmark numbers, the card's fields or a before/after value: those get quoted exactly as the commands and scripts produced them.

## Output

PR body in Markdown with the four sections, in that order.

## Escalate to the owner

- `change_card_validator` at FAIL.
- A before/after row whose two sides cannot be measured with the same command.
- A `--no-verify` (or equivalent) the owner did not explicitly authorize.
