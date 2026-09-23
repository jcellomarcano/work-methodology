---
name: change-card
description: Validates a change card in Markdown against change-card.schema.json via change_card_validator.py - 9 fields, 7 with an epistemic tag, and the opus/sonnet lane that comes out of Why/What it risks. Use it before assigning a card to a proposer, or to draft the parts of it that are missing.
version: 1.0.0
triggers:
  - validate this change card
  - change card
  - which lane does this change take
  - fields missing from the card
allowed-tools: [Read, mcp__metodo__change_card_validate, mcp__metodo__change_card_extract]
---

**IRON LAW**: it may draft missing prose; it never invents evidence or an epistemic tag the author did not give.

## Input

`<card-file>` (or `-` for stdin).

## Steps

1. `mcp__metodo__change_card_validate` with `card_path` (or `card_text` if the card is not in a file yet).
2. To read a commit body without blocking anything: `mcp__metodo__change_card_extract`.

## What the model may add

It may draft the prose text of a missing field (e.g. "How we'll know") drawing on the rest of the card, always with its own honest epistemic tag (never "Measured" for something nobody measured). It never fills in "Why" or "What it risks" on its own, nor invents the Ticket.

## Output

`{verdict, routing, fields_found, fields_missing, errors, epistemic_coverage}` exactly as the script prints it.

## Escalate to the owner

- `routing: opus` on an incomplete card.
- An empty `Invariant` on a risk field that does not accept "n/a" (Money, Payment State, Transaction Identity, Integrity, Recoverability, Security).
