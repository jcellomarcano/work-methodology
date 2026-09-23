---
name: necessary-comment
description: Runs every new comment in a diff through comment_gate.py and generic-comment-gate - the code must explain itself; a comment exists IF AND ONLY IF it states a why, short and in plain language (ISO 24495-code v0.6.2). Use it after every proposer and after the mechanic, before the adversarial round.
version: 1.0.0
triggers:
  - necessary comment
  - review diff comments
  - NEEDS-COMMENT
  - comment gate
allowed-tools: [Read, Write, Agent, mcp__metodo__comment_gate_measure, mcp__metodo__comment_gate_verify]
---

**IRON LAW**: the script locates and measures, the agent judges, the mechanic applies. No one writes a comment by hand at this step, and no number enters the minutes unless the script printed it.

## Input

`<repo>` and exactly one of `--range A..B` or `--worktree <dir>`; optional `--scope-glob G` (repeatable). The round directory (`round/`) where the numbered files get left.

## Steps

1. `mcp__metodo__comment_gate_measure` with `range=A..B` (or `worktree`) and `scope_globs`; save the output as-is as `round/NNN-comments.json`.
2. If `summary.total == 0` and `summary.markers == 0`: explicit PASS, done.
3. Brief to `generic-comment-gate` (template `04-templates/brief.md`, eight lines): `INPUTS` = `round/000-context.md`, `round/NNN-comments.json`, and the scoped diff; `OUTPUT` = the round directory, where it writes with `mcp__metodo__output_write`; `BUDGET` = 15000 tokens, 20 calls. The agent reads; the orchestrator does not paste content.
4. Verdict routing: `UNNECESSARY` (delete) and `NECESSARY` / `KDOC-INTERFACE` with `proposed_text` go to `generic-mechanic` with its exact `file:line`; `MAKE-SELF-EXPLANATORY` goes to `generic-judge`, because it touches statements and is not trivial.
5. `mcp__metodo__comment_gate_verify` with `verify_range=B..HEAD` and `range=A..B` over the mechanic's result (B = the proposer's tip): only changed comment lines and no `NEEDS-COMMENT` in the A..HEAD files; `verdict: PASS` or the round does not close.

## What the model may add

The wording of the why and the naming or extraction suggestion. Never a word count, a line the script did not list, nor a verdict on a comment the diff did not add (old code, with its own ticket only).

## Output

`round/NNN-comments.json` (script), `round/NNN-comment-verdicts.json` (agent), and the `{verdict, offending, remaining_markers}` from `--verify`. The round's minutes note `summary.total`, how many survived, and the agent's tokens.

## Escalate to the owner

- A `MAKE-SELF-EXPLANATORY` on a critical path (`config/project.json: money_paths`).
- A `NEEDS-COMMENT` the gate considers necessary but does not know how to word (`epistemic: Desconocido`).
- More than 5 new comments in a single change: a sign of code that does not explain itself, not of missing comments.
