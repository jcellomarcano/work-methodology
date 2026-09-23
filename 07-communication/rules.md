# Human-agent communication rules (COM-xx)

House rules for every reply an agent directs at a person. Same shape as the `06-languages/` conventions:
stable ID, declared detector (`active` = checked by `03-tools/lib/output_lint.py`; `proposed` = judged by a
reviewer, no script yet) and source. The source ids (A#, O#, G#, L#, E#, N#) live in `sources/`. Thresholds
live in `03-tools/config/output-lint.json`; changing them is a change with a card. Every rule has two or
three of the four source families behind it, never all four, and COM-08, COM-17, COM-18 and COM-19 come from
the methodology itself or from the adversarial round, not from an external source [Measured].

## Order (the first thing the human sees)

| ID | Rule | Detector | Source |
|---|---|---|---|
| COM-01 | **Answer first.** The first line of text answers, or asks what is missing, or says no. No preamble ("Sure", "Great question!", "Good question", "As an AI", "Thanks for"). | active: first line, no opening punctuation or bold, checked against the `preambles` list | E1, E3, E14, E43, L5, L12, L32 |
| COM-02 | **Two layers.** Human layer on top; technical layer below the fixed heading `## Detalle técnico` / `## Technical detail`. A reply that exceeds `two_layers_min_lines` lines without that heading does not separate audiences. | active | E43, E46, E47, L14, G5 |
| COM-03 | **Five bullets at most** in the human layer; numbered lists are steps and do not count. Anything else nests or moves to the technical layer. | active | E30, E31, E17, L24 |
| COM-04 | **Next step, in the human layer.** Status, decision, failure and clarification replies end the human layer with `Siguiente paso:` / `Next step:` or `Necesito de ti:` / `I need from you:`. An empty marker ("none") warns. | active with `--type` | L13, L14, L34, E6 |

## Language

| ID | Rule | Detector | Source |
|---|---|---|---|
| COM-05 | **Short sentences.** In the human layer, a sentence over `sentence_warn_words` (25) words warns; over `sentence_fail_words` (40, house threshold [Assumed]) fails. | active | L29, L35, L41, L45 |
| COM-06 | **No filler.** No phrase from the `fillers` list. If the phrase wraps an irreversible warning (`irreversible_terms`), it warns instead of failing: the sentence is rewritten, the warning is kept. | active | E24, E34, L22, G12 |
| COM-07 | **Everyday words; a technical term is defined the first time** and never defined again. | proposed | L19, L20, L35, N26, N28 |
| COM-08 | **The human's language.** The reply is written in the language the person writes in; quotes and the project's own vocabulary are not translated. | active with `--lang es|en|ca|de` (stopwords of the human layer, outside quotes and code) | CONTEXT-PACK §4, protocol §3 |

## Evidence

| ID | Rule | Detector | Source |
|---|---|---|---|
| COM-09 | **An epistemic tag per unit of the technical layer.** Every bullet, table row (except the header) and paragraph carries `[Medido]`, `[Probado]`, `[Inferido]`, `[Asumido]` or `[Desconocido]`; the `No probado:` / `Not tested:` and `Siguiente paso:` / `Next step:` lines are exempt. A tag outside that vocabulary where a tag was expected (`[Cited]`, `[Recommended]`) fails; `[Docker]` mid-sentence or a `[text](url)` link does not. | active | methodology §0, why-layer §6 |
| COM-10 | **What was NOT tested, in the human layer.** Status, failure and research replies carry `No probado:` / `Not tested:` (or `Lo que NO es:` / `What it is NOT:` in a failure report) before the technical detail. | active with `--type` | methodology §7, §10 |
| COM-11 | **No repeating close.** No paragraph starting with `En resumen`, `Para concluir`, `In summary`, `To summarize`. | active | E24, E34, E43 |
| COM-19 | **Verifiable citation.** Every `path:line[-line] @ sha` and every URL in the technical layer exists where it says; a `[Medido]` or `[Probado]` unit with no citation warns (`NO_CITATION`): it may be pasted output, but nobody checks it from here. That it exists does not prove it says what is claimed: that belongs to the verifier. | active: `03-tools/lib/cite_check.py --repo <repo>` (URLs only with `--online`, declared) | methodology §0; adversarial round B-02 |
| COM-18 | **The irreversible rises.** A term from `irreversible_terms` (deletion with no copy, drop table, force push, duplicate charge, data loss...) that appears in the technical layer also appears in the human layer. | active (per-term heuristic) | adversarial round B-01; why-layer §4 |

## Analogies

| ID | Rule | Detector | Source |
|---|---|---|---|
| COM-12 | **Analogy with mapping and limit.** Every analogy ("it's like", "imagine", "like a", "think of it as") states what maps to what and, within `analogy_window_lines` following lines, where it breaks ("where it fails", "the difference is", "unlike", "breaks down"). | active (heuristic, warns) | N5, N7, N10, N11, N13 |
| COM-13 | **One explicit analogy at a time, from a familiar base, only if the concept is new to the reader.** For something complex, a second one compared against the first. | proposed | N6, N7, N11, N12, N31 |
| COM-14 | **Personal language only for the declared interlocutor.** Analogies from the personal file only when the reader is its owner and the text is not going into a shared artifact (PR, minutes, client document). | active with `--audience public` and `03-tools/config/output-lint.personal.json` (not portable; without it, declared SKIP) | N31, N32, L14 |

## Format

| ID | Rule | Detector | Source |
|---|---|---|---|
| COM-15 | **Minimal format.** No level-1 `#`; `##` and `###` at most; no long dashes (U+2014 fails, U+2013 warns); bold at most `max_bold_per_10_lines` per 10 lines; every code fence ``` closed (an open one disables the detector, so it fails). | active | kit b1013a4, A7, A9, O12 |
| COM-16 | **A list only for discrete items or steps.** The explanation goes in prose; a table when there are two dimensions. | proposed | A9, A10, L24, L41 |
| COM-17 | **What depends together, stays together.** A number with its unit, a claim with its source, code with its explanation. | proposed | E23 (single source) |

## How it is checked

```
python3 03-tools/lib/output_lint.py reply.md [--type pregunta|estado|decision|fallo|investigacion|aclaracion] [--lang es|en|ca|de] [--audience public|owner] [--allow COM-xx]
python3 03-tools/lib/cite_check.py reply.md [--repo <repo>] [--online]
```

The skill `02-skills/human-reply` chains the two and, when judgment is pending, `02-skills/human-review`.

JSON output with ordered keys: `tool_sha`, `config_sha`, `verdict` (`PASS` if no `FAIL`), `rules[]` with `id`,
`status` (`PASS` · `WARN` · `FAIL` · `SKIP`), `detector` and `evidence[]` (line and text), `layers` (lines per
layer, code fences). No timestamps or absolute paths. Same file, same output. Tests with negative control and
the real cases from the adversarial round in `03-tools/tests/test_output_lint.py`. A bench of outputs is
aggregated with `03-tools/lib/bench_output_lint.py`, which writes `results.json` and `summary.json` with the shas.

## What the script does not decide

COM-07, COM-13, COM-16 and COM-17 are judgment calls: `generic-human-reviewer` (a small model, skill
`human-review`) looks at them with this file as its rulebook and returns a table, never a rewrite. A `WARN`
does not block; `bench_output_lint.py` counts them per rule so they are not lost. If the owner disagrees with a
FAIL, `--allow COM-xx` downgrades it to a WARN and it is recorded in the output: no exception without a trace.
The lint measures shape and `cite_check.py` measures existence; whether what is cited says what is claimed
still belongs to the human verifier or the verifier agent, not to a script.

## Verdict

The four source families agree, two by two or three by three, on the conclusion first, few chunks, no
redundancy, tested with readers. No provider guide imposes answer-first or a length cap on the OUTPUT (only
prompt order and loose examples of structure, G5, O12), so these rules are imposed from outside and measured
with a script, never expected from the model.
