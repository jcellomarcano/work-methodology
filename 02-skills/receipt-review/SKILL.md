---
name: receipt-review
description: Review with receipt (RDD): freezes the candidate tree, derives the tier and runs only the review it calls for, one correction at most, then finalizes from captures. Use it on every candidate before pushing; never pushes.
version: 1.0.0
triggers:
  - review with receipt
  - open the receipt
  - receipt
  - what tier does this change take
  - close the receipt
allowed-tools: [Read, Agent, mcp__metodo__receipt_start, mcp__metodo__receipt_status, mcp__metodo__receipt_capture, mcp__metodo__receipt_finalize, mcp__metodo__receipt_acknowledge, mcp__metodo__test_sectors, mcp__metodo__verify_sectors, mcp__metodo__verify_commit, mcp__metodo__job_status, mcp__metodo__change_card_validate, mcp__metodo__comment_gate_measure, mcp__metodo__docs_lint, mcp__metodo__role_contract_validate, mcp__metodo__output_validate, mcp__metodo__route]
---

**IRON LAW**: the receipt is tied to the tree, not the commit; the tier is set by the script and stays frozen; approval is evidence about that tree, never authority to push. A ROTO gets one correction and no more.

## Input

`<repo>` with the tree committed and clean, the round directory (outside the repo), the change card (mandatory at medium and high) and the base branch.

## Steps

1. `mcp__metodo__receipt_status`: `COMMIT_FIRST` means nothing to review yet; an existing receipt for the tree is followed from its `next`.
2. `mcp__metodo__receipt_start` with `round_dir`, `change_card_path`, and `base`: read `risk.tier`, `risk.lenses`, `risk.consent`, and `budget`. Paste `RISK:`, `LENSES:`, and `RECEIPT:` into `round/000-context.md`.
3. `mcp__metodo__test_sectors`: `full_required: true` forces the high tier and the full battery (`verify_commit`).
4. Route BEFORE launching any role: `mcp__metodo__route` with `as_of` (today, typed by the orchestrator) and `task`: `task_kind` (`review`, `docs` for a docs-only diff), `tier` = `risk.tier`, `lane`, `critical_hit`, `owner_gate`, `full_required`, `owner_named` (true only when the owner asked for Fable on this task), `modules`, `lens_focus`, and `prior` (findings, disagreement, verifier FAIL, truncated, stalls, escalations so far). Settle approvals before the first launch: show each `requires_approval: true` entry to the owner, route again with `approvals: [<rule>]` for those approved, then launch once. Launch exactly the `launch: run` entries with their `model` and `effort`, copying each `max_context_tokens` (when present) into the brief's `BUDGET`; the Fable step runs as `generic-deep-reasoner`. An approval arriving after the team ran launches only the newly approved entry. Agent frontmatter is the fallback only if the tool is down. Paste `ROUTE: <rule> <inputs_hash>` into `round/000-context.md`; route again when `prior` changes. A non-`ok` status stops and goes to the owner.
5. By tier (the roles come from the roster):
   - exempt: nothing; the receipt is born approved.
   - low: scripts only. `mcp__metodo__role_contract_validate`, `mcp__metodo__comment_gate_measure`, `mcp__metodo__docs_lint`; each captured with `mcp__metodo__receipt_capture` (`role=script:role_contract`, `script:comment_gate`, `script:docs_lint`).
   - medium: the low-tier scripts, the roster's `generic-challenger` with the `lens_focus` lens (skill `adversarial-round`), and its `generic-verifier` running `mcp__metodo__verify_sectors`; the judge only if the roster runs it; all captured.
   - high: show the owner the receipt (tier, reasons, lenses, budget) and wait for OK; `mcp__metodo__receipt_acknowledge` with `decision=consent` records it. Then a full `adversarial-round`, `generic-judge`, and `generic-verifier` with `mcp__metodo__verify_commit` (`full=true`).
6. `mcp__metodo__receipt_finalize`: `approved`, `rejected`, `escalated`, or `inconclusive`, only from the captures. On `rejected`, one correction: the proposer fixes it, a new commit, `receipt_start` with `supersedes=<previous tree>`, and the tier repeats. A second `rejected` escalates to the owner; no third pass.
7. An approved receipt needs no acknowledge after the push (the push gate read it). A push without one stays in the ledger and in the PR's "What was NOT tested" (`pr-message`).

## What the model may add

Round-context prose and agent briefs. Never the tier, a model or effort the roster did not return, a capture the script rejected, or a verdict other than `receipt_finalize`'s.

## Output

The receipt at `out/rdd/<tree_sha>.receipt.json`, the numbered captures in the round directory and the minutes with tier, lenses and verdict.

## Escalate to the owner

- High tier: always, before spending (consent).
- `owner_gate: true` (a shared build file is touched): the receipt is `escalated`; the owner delivers it.
- A second `rejected` on the same card.
- Repeated `inconclusive` on one tree: the instrument or the card is wrong, not the candidate.
