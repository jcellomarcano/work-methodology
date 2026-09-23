---
name: clean-pass
description: Sweeps the repo with clean-pass.sh (long files, long functions, var/lateinit, duplication, boundaries) and turns every flagged item into a change card for the proposer, one at a time. Use it for accumulated technical debt, never in the middle of an ongoing critical change.
version: 1.0.0
triggers:
  - clean pass
  - technical debt sweep
  - clean up this module
  - clean pass
allowed-tools: [Read, Agent, mcp__metodo__clean_pass, mcp__metodo__change_card_validate]
---

**IRON LAW**: it proposes only on items the script flagged. No item `clean-pass.sh` did not flag enters as a proposal.

## Input

`<repo>`.

## Steps

1. `mcp__metodo__clean_pass` on `<repo>`; if it arrives with `truncated_inline: true`, read the `.md` at `out_md`.
2. For each flagged item, draft a change card and validate it with `mcp__metodo__change_card_validate` (`card_text`).
3. Hand the card to `generic-proposer` (Agent), one at a time, never in batch.

## What the model may add

Drafting the card (Why, How, etc.) for each flagged item. It never adds its own item to the list `clean-pass.sh` gave.

## Output

N change cards, one per flagged item, each handed to a different `generic-proposer`.

## Escalate to the owner

- A flagged item falls within the money/critical-flow paths declared in `config/project.json` (`money_paths`), or any opus-lane path: before turning it into a card, not after.
