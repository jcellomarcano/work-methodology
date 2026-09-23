# Minutes · round of two adversaries on 07-communication/ and output_lint.py (09-Sep-2026)

Scope: the whole folder plus `03-tools/lib/output_lint.py`, its config and its tests, before they were
written into the kit (no sha: new folder, uncommitted). Adversaries: challenger (large model, 24 findings: 11
BROKEN, 11 NUANCE, 2 OK; 29 calls, 139k tokens) and blind-spot adversary (large model, 19 gaps: 16 OPEN WITH
OWNER, 3 CONTAINED, 0 CLOSED; 30 calls, 122k tokens). Both ran nine inputs built against the lint. Rule
applied: a BROKEN gets fixed before it is written into the kit; an OPEN needs an owner; what belongs to the
script was closed here, and what belongs to the owner is presented to them. No judge: the orchestrator
resolved it and wrote it down.

## Confronter: resolution

| Id | Verdict | What was wrong | Fix applied or reason for rejection |
|---|---|---|---|
| C-01 | BROKEN | the `templates.md` skeletons failed the lint (`[tag]` as a placeholder) | real tags in the skeletons; test `test_every_template_skeleton_passes_its_type` over the 7 blocks [Probado] |
| C-02 | BROKEN | COM-08 counted English quotes as a language switch | stopwords only in the human layer and outside quotes and code; test with a literal quote [Probado] |
| C-03 | BROKEN | `[Docker]` and `[text](url)` failed COM-09 | an unknown tag fails only at the start or end of the unit; test [Probado] |
| C-04 | BROKEN | "Sure thing!" passed COM-01 | opening punctuation, quotes and bold are stripped before comparing; test [Probado] |
| C-05 | BROKEN | `Next step:` hidden in the technical layer passed COM-04 | COM-04 and COM-10 search only the human layer; test [Probado] |
| C-06 | BROKEN | COM-14 was case-sensitive and missing 4 of 7 meme tags | `re.IGNORECASE`, expanded list (71 terms) in a separate file; test with `jedi`, `Dagobah`, `[bad feeling]` [Probado] |
| C-07 | NUANCE | untagged prose in the technical layer passed | COM-09 per unit: bullet, table row and paragraph; test [Probado] |
| C-08 | NUANCE | "three to five points" only checked the five | renamed "five bullets at most"; numbered ones do not count (B-04) |
| C-09 | BROKEN | "converge on four rules" with no row showing all four families | reworded as it is: two by two or three by three, never all four (`research.md`, `rules.md`) |
| C-10 | BROKEN | "every rule has two or more sources"; the 40-word threshold with no source | reworded to "most"; COM-17 declared as single-source; 40 marked [Asumido] |
| C-11 | BROKEN | "one analogy per concept" backed by sources that say the opposite | rule and block: one explicit at a time, a second one compared for something complex; "per concept" is dropped |
| C-12 | NUANCE | "no provider talks about the output" overgeneralized | narrowed: they do not impose answer-first or a cap; G5 and O12 cited as loose structure examples |
| C-13 | BROKEN | `results.json` had no sha despite what the minutes said | `bench_output_lint.py` writes `tool_sha` and `config_sha` into `results.json` and `summary.json` |
| C-14 | OK | the minutes' arithmetic | recalculated by the challenger from `results.json`: 0 discrepancies out of 30 |
| C-15 | NUANCE | the criterion did not declare the tautology (the lint measures obedience to the block) | declared in the minutes, in `research.md` §5 and in the README |
| C-16 | NUANCE | the aggregates were re-derived by the model | `bench_output_lint.py` with a test; the minutes copy its numbers |
| C-17 | BROKEN | `AGENTS.md` had a placeholder instead of the block | block pasted in via documented command (`AGENTS.head.md` + `identity.en.md`) |
| C-18 | NUANCE | `docs-caps.json` was not delivered in the container | it exists in the owner's kit; updated when the folder is written (authorized gate) |
| C-19 | NUANCE | `03-tools/...` paths did not exist in the container | they are kit paths; resolved once written; "from the kit root" added |
| C-20 | NUANCE | "measured differences" per provider | reworded to "documented per provider (read, not measured by this kit)" |
| C-21 | NUANCE | "three options at most" with no id or source | dropped; options count like COM-03's points |
| C-22 | NUANCE | `truncated: False` dead constant | removed |
| C-23 | OK | 26 tests with negative control | holds; now 29 |
| C-24 | NUANCE | the long-dash exception did not cover the detector | exception widened in the folder's README |

## Blind-spot adversary: resolution

Closed in the deliverable: B-01 (COM-18, the irreversible rises; test for the real case), B-03 (COM-06 warns
instead of failing when the filler wraps an irreversible warning), B-04 (numbered lists do not count toward
COM-03), B-05 (an unclosed fence fails COM-15), B-06 (`--lang ca|de` with their own stopwords), B-07 (COM-14
was case-sensitive, memes included), B-08 (the name and interests are out of the pasteable block and the
portable config: `--audience owner`, `output-lint.personal.json` kept separate), B-10 (WARNs counted per rule
in `summary.json` and in the minutes), B-11 (`--allow COM-xx` leaves a trace; the style reviewer still has no
brief, open), B-13 (COM-09 and code-fence regressions noted in the minutes), B-14 (= C-17), B-17 (an empty
marker warns), B-19 (an `aclaracion` type and the instruction to ask or refuse in the first line).

Contained, no decision made: B-12 (the bench pre-loads the data: the risk of inventing was not measured,
noted in the minutes), B-16 (the block does not pass its own lint because it quotes fillers; declared in the README).

Decided by the owner the same day (id, decision, where it landed):
- B-02: "always verify": `03-tools/lib/cite_check.py` (COM-19) checks `path:line @ sha` and URLs; tests with
  a temporary git repo in `test_cite_check.py`. Whether the citation says what is claimed is still the verifier's job.
- B-09: cadence proposed by the orchestrator and accepted as [Asumido]: a card for every threshold or rule
  change, the bench re-run on a model version change, quarterly review of the personal list and the WARNs (README §Maintenance).
- B-11: skill `02-skills/human-review` with agent `generic-human-reviewer` (haiku, 15k, Read only) for
  COM-07/12/13/16/17; returns a table, never a rewrite.
- B-15: skill `02-skills/human-reply` chains `output_lint.py` and `cite_check.py`, two passes at most,
  and escalates any `--allow`, `COM-18` or `MISSING` citation to the owner. Both skills go into `install-claude.sh`.
- B-18: the model asks "is this going to anyone else?" before using a personal-language file (owner-local,
  skill `human-reply` step 1).
- C-18/C-19: folder, scripts, config and tests written into the kit; `README.md` and `docs-caps.json`
  registered; `docs_lint` and 35 tests green on the owner's Mac.

## What this round did NOT prove

It did not run on the kit as written to disk (it ran on the working container); it did not test `docs_lint.py`
against the new caps until they were written; it did not measure GPT or Gemini; it did not read the four
`sources/` dossiers quote by quote: the challenger reported no mismatches between ids and dossiers, but did
not report how many ids it checked, so the id-to-quote correspondence stays [Desconocido] except for what
both sets of minutes cite. n of the experiment: 9 adversarial inputs per adversary.
