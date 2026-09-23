---
name: human-review
description: Briefs generic-human-reviewer (small model) to judge the communication rules no script decides - COM-07 defined terms, COM-12 and COM-13 analogies with a mapping and a limit, COM-16 list or prose, COM-17 keeping dependent things together - with 07-communication/rules.md as the rulebook. Use it after human-reply when the reply carries an analogy, a long list, a new technical term, or figures.
version: 1.0.0
triggers:
  - human review
  - review analogy
  - reply style reviewer
  - COM-07
  - COM-13
allowed-tools: [Read, Agent]
---

**IRON LAW**: the reviewer flags against the rule's text, never against taste; no rule id, no finding. The reviewer does not rewrite: it returns a table and the author fixes it.

## Input

The reply already at `PASS` from `output_lint.py` (this skill does not replace `human-reply`: it runs after it), its `.lint.json`, and who the reader is (`public` or `owner`).

## Steps

1. Brief to `generic-human-reviewer` with the `04-templates/brief.md` template (eight lines): `INPUTS` = the reply and `07-communication/rules.md`; `CONSTRAINTS` = rules COM-07, COM-12, COM-13, COM-16, COM-17 and the declared reader; `OUTPUT` = the round directory, where the reviewer writes with `mcp__metodo__output_write` (schema `human-reviewer-output`); `BUDGET` = 15000 tokens, 10 calls.
2. Read the verdict. An explicit `PASS` with zero findings is a legitimate outcome.
3. Every finding goes back to the reply's author (the model that wrote it, or the mechanic if it is trivial) with its `fix_hint`; the reviewer never applies the fix.
4. After fixing, repeat `human-reply` (the lint) and, if the fix touched an analogy, this skill once more. Two passes at most.

## What the model may add

The reviewer may propose a one-line `fix_hint` (rename the term, state the mapping, split the list into prose). Never the full text, never a rule outside the five, never a verdict on the technical layer (that belongs to `cite_check.py` and the verifier).

## Output

`<reply>.review.json` (`verdict`, `violations[]` with `rule`, `line`, `statement`, `fix_hint`, `epistemic`). The minutes note how many findings, how many survived, and the reviewer's tokens.

## Escalate to the owner

- A COM-13 finding on an analogy from the owner's own personal-language file (if the project keeps one, kept local and out of this kit): its owner decides the mapping; if it is false, the row gets deleted.
- Two passes without `PASS`: the rule is not clear or the reply does not fit it.
