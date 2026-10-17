# 07-communication · how an agent talks to a person

Human-agent communication only. What agents say to each other stays in `00-principles/agent-protocol.md`.
The idea in one sentence: the answer first, in two layers (human and technical), measured with a script and
never trusted to the model. Multi-LLM: one identity block and a thin adapter per provider.

## Start here

1. `identidad.es.md` (or `identity.en.md`): the block pasted into the system prompt. It is everything a
   model needs; the rest of the folder explains why it says what it says and how that is checked.
2. `rules.md`: the 19 COM-xx rules with their detector and source.
3. `templates.md`: the six skeletons (question, status, decision, failure, research, clarification or refusal).

## Map

| File | Content | Cap |
|---|---|---|
| `identidad.es.md` / `identity.en.md` | pasteable block, two versions that say the same thing | 100 each |
| `rules.md` | COM-01..19, detector `active` or `proposed`, source ids | 100 |
| `templates.md` | skeleton and example per reply type; what the lint requires of each type; tested by `test_output_lint.py` | 150 |
| `research.md` | contrast across the four source families: agree, differ, nobody says; sourced decisions | 120 |
| (owner's personal-language file, optional) | dictionary of analogies and memes for a single named reader only; kept local, not part of this kit | 90 |
| `adapters/` | `CLAUDE.md`, `AGENTS.md` (with the block pasted in), `GEMINI.md` and their README with the differences documented per provider | |
| `sources/` | four dossiers with literal quotes in their own language and URL (providers, plain language, executive and cognitive, analogies); no cap | |
| `bench/` | fixed prompts, briefs for both arms, cold-test outputs (`out/` with identity v2, `out-v1/` with v1), `results.json` and `summary.json` written by script | |
| `minutes/` | minutes for each measurement, with what was NOT tested | |
| `03-tools/lib/output_lint.py` | the detector: ordered JSON, `tool_sha`, `config_sha`; config in `03-tools/config/output-lint.json`; personal terms in `output-lint.personal.json` (not portable); tests in `03-tools/tests/test_output_lint.py` | |
| `03-tools/lib/bench_output_lint.py` | aggregates a bench of outputs into `results.json` and `summary.json`; the minutes copy its numbers, never re-derive them | |
| `03-tools/lib/cite_check.py` | checks that every `path:line @ sha` and every URL in the technical layer exists (COM-19); tests in `test_cite_check.py` | |
| `02-skills/human-reply`, `02-skills/human-review` | the skill that chains lint and citations before sending, and the one that briefs `generic-human-reviewer` (`01-roles/agents/`) for the judgment rules | |
| `02-skills/review-comment` | code review comment: `pr_scope.py` separates what belongs to the PR from base-branch noise; one paragraph with What happens / Why it happens / How it affects / How to fix, plus a proposal in the file's own language; `review_comment_lint.py` (RC-01..07, config `review-comment.json`) | |

## Day-to-day use

- Claude Code: `@07-communication/identidad.es.md` from the user's or repo's `CLAUDE.md` (`adapters/CLAUDE.md`).
- Codex: `adapters/AGENTS.md` carries the block pasted in (no import); regenerate it with the command in `adapters/README.md`; `verbosity: low` in the API.
- Gemini CLI: `@07-communication/identidad.es.md` from `GEMINI.md`; in the API, `system_instruction`.
- Before sending a reply that matters: skill `human-reply` (lint + citations; by hand: `python3 03-tools/lib/output_lint.py ...` and `python3 03-tools/lib/cite_check.py ... --repo <repo>`, from the kit root). With an analogy, a long list or a new term, follow up with `human-review`.
- To use a personal language file: the activation line goes in the user-level file, never in the repo one; the model asks "is this going to anyone else?" before using it; the lint on a shared artifact runs with `--audience public`.

## Maintenance (owner's decision, 09-Sep-2026)

Owner: the owner. Every threshold change in `output-lint.json` or rule change in `rules.md` carries a change
card and the bench (`bench_output_lint.py`) is re-run to see what it moves. Review by event: when the version
of a model in use changes (Claude, GPT, Gemini), the bench is re-run with that model before trusting the block;
when a provider changes its guidance, `sources/vendors.md` is updated with the new quote and date. Review
by calendar: once a quarter, any personal-language file and `output-lint.personal.json` (delete false mappings, add
new terms) and the accumulated `WARN`s in `summary.json`. Everything stays [Assumed] until the first real review.

## What was measured and what wasn't

Cold test from 09-Sep-2026 with three sizes of Claude and identity v2: lint PASS 1/15 without identity, 8/15
with it [Measured]. The lint measures obedience to the block, not comprehension. GPT, Gemini, local models and
comprehension by human readers: not measured, procedure in the minutes. Adversarial round the same day: 24
attacks and 19 blind spots; the BROKEN ones are fixed and the OPEN WITH OWNER ones were decided by the owner
the same day (round minutes in `minutes/`).

## Rules specific to this folder

- Documents in English with a line cap in `docs-caps.json`; `sources/` and `bench/` have no cap, because they are evidence.
- Quotes are copied literally and in their own language; a quote not read on its own page is `[Inferred]` or `[Unknown]`.
- A personal-language file is never installed into any repo and never enters a shared artifact; the lint with
  `--audience public` watches for that.
- No long dashes in any file, as in the rest of the kit. Declared exception: inside `sources/` and
  `bench/out*/` the quotes and outputs are kept byte for byte (protocol §3), dashes included; and the
  detector itself and its tests contain them because they search for them.
- `identidad.*.md` is a document, not a reply: it is not run through the lint (it quotes fillers in order to ban them).
