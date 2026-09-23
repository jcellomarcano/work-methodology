---
name: pr-message
description: PR message with the change_card_validator gate (and, for release PRs, benchmark-release) already embedded. Use it when opening the PR for a change with a card, or the PR for a release.
version: 1.0.0
triggers:
  - pr message
  - open the pr
  - pr template
  - release pr
allowed-tools: [Read, Agent, mcp__metodo__change_card_validate, mcp__metodo__benchmark_release, mcp__metodo__job_status, mcp__metodo__receipt_status]
---

**IRON LAW**: every skipped check (`--no-verify` or equivalent) goes in "What was NOT tested", never kept quiet.

## Input

`<repo>`, the change card, and for release PRs: `<lastTag>` and `<candidate>`.

## Steps

1. `mcp__metodo__change_card_validate` with `card_path`; a FAIL blocks the message.
2. If it is a release PR: `mcp__metodo__benchmark_release` with `ref_a=<lastTag>` and `ref_b=<candidate>`, and `mcp__metodo__job_status` until `done`.
3. `mcp__metodo__receipt_status` on the repo: copy as-is into "What was NOT tested" whatever the receipt says was missing (`verdict_reasons`, missing captures, `skipped_no_credential` from `verify_sectors`, any `owner_ack` of delivery without a receipt) and any `--no-verify`; never summarize it.
4. Draft the body in this order: **What and why** (in customer-facing language if it is a release PR), then a `<!-- -->` block with the card, the receipt's verdict, and the Benchmark section, then **What was NOT tested**.

## Checklist

Comments: every new comment says a why the code cannot (DOC-001); every new KDoc opens with a summary
fragment and carries no tag the signature already says (DOC-002); every action tag is `TODO(KEY-###):`
with `KEY` among the project keys in `config/project.json:ticket_keys` (today `DEV` and `POS`), and no
`NEEDS-COMMENT` remains (DOC-003).

## What the model may add

The "What and why" prose. Never the benchmark numbers or the card's fields, those get quoted exactly as the scripts produced them.

## Output

PR body in Markdown with the three sections, in that order.

## Escalate to the owner

- `change_card_validator` at FAIL.
- A `--no-verify` (or equivalent) the owner did not explicitly authorize.
