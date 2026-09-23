# Minutes · cold test of the response identity (09-Sep-2026, Claude subagents in Cowork, the owner's session)

Build: identity v2 (`identidad.es.md`), `output_lint.py` tool_sha `17d607d4d78d`, config_sha `3c162e8277fc`
(written by `bench_output_lint.py` into `bench/summary.json`); kit @ 39ead7a plus the `07-communication/` folder
uncommitted. Simulations or stand-ins: none; all three models answered for real. Instrument verified before
measuring: `test_output_lint.py` and `test_bench_output_lint.py` (29 tests, negative control per rule) green.
Declared observer effect: the models ran as Claude Code subagents, not against the raw API; the harness adds
its own system prompt to both arms equally. n = 1 per cell; medians are across prompts, not across repeats.
The numbers in these minutes are written by `bench_output_lint.py`; nobody re-derives them.

Single variable: the identity block ahead of the prompt (`bench/briefs/P*-con.txt`) versus the prompt alone
(`P*-sin.txt`). Primary metric, declared before running: proportion of outputs with `verdict: PASS` in
`output_lint.py --type <type> --lang es --audience public`. Success criterion: the arm with identity beats
the control across all three sizes. Declared threat to validity: the lint encodes instructions that only the
identity arm received, so the metric measures obedience to the block, not comprehension; the effect is partly
tautological [Inferido]. The prompts carry the data the reply needs inside them, so the risk of inventing
when data is missing was not measured.

| Arm | Single variable | Primary metric | Criterion (set beforehand) | n | Result | Median word count | Technical layer present | Total FAILs |
|---|---|---|---|---|---|---|---|---|
| A (control) | no identity | lint PASS | baseline | 15 | 1 / 15 | 362 | 0 / 15 | 46 |
| B | with identity v2 | lint PASS | > A across all three sizes | 15 | 8 / 15 | 231 | 11 / 15 | 7 |

By size (n = 5 per cell, PASS and median word count): Haiku 1/5 and 152 → 3/5 and 154; Sonnet 0/5 and 365 →
3/5 and 231; Opus 0/5 and 571 → 2/5 and 491. Criterion met across all three [Medido].

## What fails without identity and what holds up with it (FAILs out of 15)

| Rule | A | B | Reading |
|---|---|---|---|
| COM-04 next step in the human layer | 9 | 1 | Sonnet omits `Necesito de ti` once (decision) |
| COM-10 what was not tested, in the human layer | 9 | 0 | |
| COM-05 sentences over 40 words | 8 | 1 | Opus, research report |
| COM-02 two layers | 7 | 0 | no control separates layers; 11 of 15 with identity do |
| COM-15 minimal format | 6 | 1 | Haiku, one long dash in the research report |
| COM-03 more than five bullets | 3 | 0 | |
| COM-01 answer first | 3 | 0 | |
| COM-11 repeating close | 1 | 0 | |
| COM-09 epistemic tag per unit | 0 (SKIP: no layer) | 4 | see "never worse than before" |

WARN (warn, do not block): A `COM-05` 3, `COM-15` 3; B `COM-05` 6, `COM-12` 1, `COM-15` 1. Long-sentence WARNs
rise with identity: the block shortens the reply but not the sentence [Medido].

## Never worse than before: what identity makes worse

- COM-09 goes from 0 to 4 FAILs, because without identity there is no technical layer to tag, and with it
  the models invent tags (`[Recomendado]`, `[Crítico]`, Haiku) or leave prose untagged (Opus, Sonnet). It is
  the new failure mode identity creates; the lint sees it [Medido].
- Code-fence lines: 4 in A (two replies with a code block), 0 in B. Identity may be removing code blocks
  where they helped; with n = 15 this is not conclusive [Inferido].
- Refusals, clarifying questions, legitimately long replies and multi-turn conversations: not measured.

## Measurement history (own mistakes count too)

First pass (identity v1, lint v1): B = 5/15, with seven COM-09 FAILs over `- No probado:` bullets that the
identity itself required; the detector was punishing what the rule demanded. Fixed with two tests for the
real case; second v1 pass: 10/15. The same-day adversarial round (separate minutes) took down five more
detectors (preamble with `¡`, a marker hidden in the technical layer, untagged prose, an English quote
counted as a language switch, an unclosed fence) and moved `No probado` into the human layer; with that lint
v1 scored 8/15. Identity v2 was re-run in full on arm B (the 15 outputs in `bench/out/`; the v1 ones stay in
`bench/out-v1/`); arm A is the same prompt, reused. The numbers above are v2 with lint v2 [Medido].

Pasted evidence: `bench/results.json` (30 rows: file, model, arm, type, verdict, FAIL, WARN, lines, words,
fences) and `bench/summary.json` (aggregates and shas), both written by `bench_output_lint.py`; full outputs
in `bench/out/`; prompts in `bench/prompts.md`.

## What these minutes do NOT prove

- Nothing about GPT or Gemini: `not_measured`. Procedure: same `bench/briefs/*`, the block in `developer`
  with `verbosity: low` (GPT) or in `system_instruction` (Gemini), same 30 cells, same lint and same aggregator.
- Nothing about local open models.
- Nothing about real human comprehension: the lint measures shape, not whether a person understands better.
  That needs a paraphrase test with readers (source L25) and stays [Desconocido].
- n = 1 per cell: variation across runs of the same model is not measured.
- The `proposed` rules (COM-07, 13, 16, 17) were not measured: they have no detector or reviewer with a brief.
- Analogies: only the research prompt called for them; one COM-12 WARN across 30 outputs; without separating
  "well closed" from "absent" [Desconocido].
- Whether a `[Medido]` tag is true, or a figure actually exists: no script sees that (blind spot B-02).

Associated change card: none (new folder, no product code). Invariants touched: none.
