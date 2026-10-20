---
name: harness-benchmark
description: Use whenever asked to measure, benchmark or compare a harness, kit, methodology, review setup, model/effort choice, or "with vs without" a tool. Never compares setups from one run or from impressions.
version: 1.0.0
triggers:
  - benchmark the harness
  - measure the kit
  - compare with and without
  - is the kit worth it
  - compare review setups
  - compare models or effort
  - harness-benchmark
allowed-tools: [Read, Bash]
---

**IRON LAW**: never compare setups from one run or from impressions. Every number keeps its label
(Measured, Tested, Inferred, Assumed, Unknown) and its n. An arm without evidence in its transcript
that its setup ran is `invalid-arm`: it is reported, never scored.

Vanilla install: copy this folder to `~/.claude/skills/harness-benchmark/` (or a repo's
`.claude/skills/`). Inside the kit the installer ships it. Python 3 stdlib only, nothing else.

## Input

- Observational question ("what happened in my sessions?"): a repo path or a substring of the
  transcript dir name, optionally a start date.
- Comparison ("is setup A better than B?"): an `ab.json` config with the task prompts, the arms, `k`
  (default 3), one model and one effort for every arm.

## Steps

1. Locate the scripts: `B="$(dirname <path of this SKILL.md>)/bench.py"`. They sit next to this file
   whether the folder was copied by hand or installed by the kit.
2. Observational: `python3 "$B" session --project <repo> [--since YYYY-MM-DD] --out <dir>`. Add
   `--window-table <json>` when the model's context window differs from the built-in table. Read
   `<dir>/session-report.md`.
3. Comparison: first state the cost (runs = tasks × arms × k, each a full `claude -p` session) and ask
   the owner before launching. Then `python3 "$B" ab --config ab.json --out <run>` (try `--dry-run`
   first), `python3 "$B" judge --run <run>`, `python3 "$B" report --run <run>`. `--preset
   kit-vs-vanilla` gives four arms: `vanilla` (no kit file, no skills, no MCP), `kit-neutral` (kit
   copied in, neutral prompt), `kit-invoked` (prompt runs the kit's review), `native` (Claude Code's
   `code-review`). Each run uses a fresh worktree outside the repo; `--out` must be outside it too.
   Judges: deterministic checks first (`verify`, `seeded`); then two model families when you can, both
   orders. Lead with activation, spend and cost per solved task, and seeded recall.
4. Relay the report's "signal vs conclusion" line verbatim, with the n beside every comparison.

Optional reading, only when the repo has it: `08-benchmark/protocols/`. The skill works without it.

## What the model may add

Prose on what the numbers suggest and which confound might explain them, every sentence tagged.
It never recomputes, rounds or drops a number, never relabels `Unknown` as a value, and never
attributes an observational difference to a harness except as Inferred.

## Output

The report's path, its "signal vs conclusion" line, the headline rows with label and n (activation,
cost per solved task, tokens by type, peak context, steering), and every `not-run`, `failed` or
`invalid-arm` row.

## Escalate to the owner

- Before any `ab` run (it spends money and time).
- An arm comes out `invalid-arm`, or k < 3 is requested for a comparison.
- The report shows a difference whose CI crosses zero and someone wants it stated as a result.
