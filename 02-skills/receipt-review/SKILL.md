---
name: receipt-review
description: Review with receipt (RDD) - freezes the candidate by its tree with receipt_start, derives the tier (exempt, low, medium, high) and runs only the review that tier calls for; one correction at most; receipt_finalize closes from the captures. Use it on every candidate before pushing; approval never pushes or opens a PR.
version: 1.0.0
triggers:
  - review with receipt
  - open the receipt
  - receipt
  - what tier does this change take
  - close the receipt
allowed-tools: [Read, Agent, mcp__metodo__receipt_start, mcp__metodo__receipt_status, mcp__metodo__receipt_capture, mcp__metodo__receipt_finalize, mcp__metodo__receipt_acknowledge, mcp__metodo__test_sectors, mcp__metodo__verify_sectors, mcp__metodo__verify_commit, mcp__metodo__job_status, mcp__metodo__change_card_validate, mcp__metodo__comment_gate_measure, mcp__metodo__docs_lint, mcp__metodo__role_contract_validate, mcp__metodo__output_validate]
---

**IRON LAW**: the receipt is tied to the tree, not the commit; the tier is set by the script and stays frozen; approval is evidence about that tree, never authority to push. A ROTO gets one correction and no more.

## Input

`<repo>` with the tree committed and clean, the round directory (outside the repo), the change card (mandatory at medium and high), and the base branch.

## Steps

1. `mcp__metodo__receipt_status`: if it says `COMMIT_FIRST`, there is nothing to review yet. If there is already a receipt for the tree, follow it from its `next`.
2. `mcp__metodo__receipt_start` with `round_dir`, `change_card_path`, and `base`: read `risk.tier`, `risk.lenses`, `risk.consent`, and `budget`. Paste `RISK:`, `LENSES:`, and `RECEIPT:` into `round/000-context.md`.
3. `mcp__metodo__test_sectors`: if it returns `full_required: true`, the review runs at the high tier no matter what, and the battery is the full one (`verify_commit`).
4. By tier:
   - exempt: nothing; the receipt is born approved.
   - low: scripts only. `mcp__metodo__role_contract_validate`, `mcp__metodo__comment_gate_measure`, `mcp__metodo__docs_lint`; each output gets tied in with `mcp__metodo__receipt_capture` (`role=script:role_contract`, `script:comment_gate`, `script:docs_lint`).
   - medium: the low-tier scripts, a `generic-challenger` (sonnet) with the `lens_focus` lens (skill `adversarial-round`), and a `generic-verifier` that runs `mcp__metodo__verify_sectors`; both captured.
   - high: show the receipt to the owner (tier, reasons, lenses, budget) and wait for their OK; `mcp__metodo__receipt_acknowledge` with `decision=consent` records it. Then a full `adversarial-round` on opus, `generic-judge`, and `generic-verifier` with `mcp__metodo__verify_commit` (`full=true`).
5. `mcp__metodo__receipt_finalize`: `approved`, `rejected`, `escalated`, or `inconclusive`, only from the captures. On `rejected`, one correction: the proposer fixes it, a new commit, `receipt_start` with `supersedes=<previous tree>`, and the tier repeats. A second `rejected` escalates to the owner; there is no third pass.
6. After the push, `mcp__metodo__receipt_acknowledge` is not needed for an approved receipt: the push gate already read it. A push without an approved receipt stays in the ledger and in "What was NOT tested" on the PR (`pr-message`).

## What the model may add

The round-context prose and each agent's brief. Never the tier (that comes from `receipt_start`), never a capture the script rejected, never a verdict different from what `receipt_finalize` returned.

## Output

The receipt at `out/rdd/<tree_sha>.receipt.json`, the numbered captures in the round directory, and the minutes with the tier, the lenses, and the verdict.

## Escalate to the owner

- High tier: always, before spending (consent).
- `owner_gate: true` (the change touches a shared build file): the receipt comes out `escalated` and the owner delivers it.
- A second `rejected` on the same card.
- Repeated `inconclusive` on the same tree: the instrument or the card is wrong, not the candidate.
