---
name: adversarial-round
description: Round of two adversaries - challenger and blind-spot adversary attack the same claims with the same facts (domain_invariants + dep_boundaries), each with its own lens and vocabulary. Use it when there is a change card or a claims map ready to attack, before the judge rules.
version: 1.0.0
triggers:
  - adversarial round
  - attack this change
  - challenger and blind spots
  - two adversaries on the same card
allowed-tools: [Read, Agent, mcp__metodo__domain_invariants, mcp__metodo__dep_boundaries, mcp__metodo__change_card_validate, mcp__metodo__receipt_status, mcp__metodo__output_validate, mcp__metodo__receipt_capture]
---

**IRON LAW**: ABIERTO beats OK until the judge rules. A truncated round is not a silent PASS, it is INCOMPLETE.

## Input

`<repo>`, the change card or the claims map (`claims.schema.json`), the diff if there is one.

## Steps

1. Facts, the same for both adversaries: `mcp__metodo__domain_invariants` and `mcp__metodo__dep_boundaries` on `<repo>`; the facts file is `out/<repo_sha>/domain-invariants.json` plus `deps.json` (paths in the brief, never content pasted in).
2. Lane and tier: `mcp__metodo__change_card_validate` with `card_path` and read `routing`. If a receipt is open, `mcp__metodo__receipt_status` returns the frozen tier and lenses: those rule. Opus lane also applies if the diff touches `money_paths`, whatever the card says.
3. Medium tier: only `generic-challenger` (sonnet) with the receipt's `lens_focus` lens. High tier: in parallel and with the same facts file, `generic-challenger` and `generic-blind-spot-adversary` (Agent) on opus, and only with `risk.consent: granted` in the receipt.
4. Each adversary writes its document with `mcp__metodo__output_write` (its Stop hook validates it on close). If a loose file reaches you, `mcp__metodo__output_validate` with `schema=findings` or `schema=blindspots`.
5. If either output arrives with `truncated: true`, the whole round is INCOMPLETE, never PASS.
6. Tie each output to the receipt with `mcp__metodo__receipt_capture` (`tree`, `role`, `artifact_path`, `handoff_to=judge`); the script leaves the numbered handoff, with its shas.

## What the model may add

A prose summary of how the two lenses combine (where they agree, where they do not); it never resolves the ruling on its own, that is the judge's work.

## Output

The two documents (`findings.schema.json`, `blindspots.schema.json`) plus the round's status: OK / INCOMPLETE / pending judge.

## Escalate to the owner

- Opus lane without budget for both full rounds.
- Confronter and blind-spot adversary contradict each other on the same `file:line`.
