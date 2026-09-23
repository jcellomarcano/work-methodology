# Review receipt (RDD) · v1

Adaptation of Receipt-Driven Development (gentle-ai, `docs/architecture/organic-rdd.md`, read
15-sep-2026) for the kit. Cap: 60 lines. Scripts: `03-tools/lib/rdd_receipt.py`, `rdd_risk.py`; hooks in
`03-tools/hooks/`; skill `receipt-review`.

## 1. What a receipt is

Review follows the work: a committed candidate exists first, then exactly that candidate gets reviewed.
The receipt (`out/rdd/<tree_sha>.receipt.json`) freezes what's reviewed, at what depth, with what
budget, and under what card, and ties every artifact of the round to it by sha256. No field is filled in
by an agent.

## 2. Identity: the tree, not the commit

`tree_sha = git rev-parse HEAD^{tree}`. An amend that only changes the message keeps the receipt; a
rebase that changes the tree invalidates it. Real case: the same commit sha wasn't the same tree across
CI's PR previews. A dirty tree opens no receipt (`next: COMMIT_FIRST`).

## 3. Four layers and their lenses

| Layer | When (first matching row in `rdd_risk.py`) | What runs |
|---|---|---|
| exempt | no paths, or only `exempt_globs` (docs) | nothing; born approved |
| high | shared build (+ owner gate), `money_paths`, opus lane | two adversaries on opus, judge, full battery; prior consent |
| low | tests or docs only; or `What it risks: none` with a small diff | scripts only: contract, comments, docs |
| medium | everything else (and no card, which `start` requires) | one challenger on sonnet with one lens + sector verifier |

RDD's 4Rs are the lenses of the high layer: Risk = `critical-flow`; Resilience = `never-worse-than-before`;
Readability = `simplicity` + DOC-001 by scripts; Reliability = `anti-flake-tests`. Medium carries one, the
first that matches the touched paths (`lens_paths`). `test_sectors.full_required` bumps the layer to high.

## 4. States and one correction

`started -> captured -> finalized/{approved, rejected, escalated, inconclusive}`. `finalize` only reads
captures: a truncated capture or a missing mandatory role -> inconclusive; a verifier FAIL or BROKEN
without REFUTED -> rejected; UNRESOLVED, OPEN WITH OWNER without a fail or the owner's gate -> escalated.
A `rejected` allows `start --supersedes` once on the same card; the second one escalates. An approval at
the low or medium layer is inherited (`--inherit-from`) if the candidate's files come out byte-identical
after the rebase; high repeats.

## 5. What the harness applies

Whatever the harness can apply, the harness applies, the model doesn't have to remember it. Always
blocked: subagent edits to shared build files and `.claude/`, `git push --force` without lease, delivery
by subagents, the contract's call budget. Under `rdd.mode` (`warn` first, `block` after the measured
week): the push/PR gate without a receipt (`ask` the owner), each role's JSON output on close, the
response lint. Everything lands in `out/hooks/<session>/ledger.jsonl`; `hooks_report.py` decides the move
to block.

## 6. What it does NOT do

It doesn't push, doesn't open a PR, doesn't merge, doesn't tag: delivery belongs to the owner. It doesn't
replace the repo's pre-push or CI. It doesn't measure tokens. It doesn't run on another project without
its `project.json` (`rdd`, `test_sectors`).
