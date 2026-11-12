# Kit audit, November 2026: what stands between this kit and team adoption

The kit's ideas hold up and three of them are rare in the market. What blocks adoption is not the method:
the kit lives in two trees that share no history, most rules warn instead of block, the proof that it works
is one pull request, and only two of five runtimes are wired. This audit lists each gap with its evidence
and the order to close them.

Measured on `fc3f968` (branch `feat/data-practice-and-pr-before-after`) on 2026-11-12 by four read-only
mappers; the parent re-ran one command per map. Feature document: `odd/tasks/kit-audit-goal-contract.md`. Tags: Measured, Tested, Inferred, Assumed, Unknown. Market
facts carry their source id and come from `reports/Panorama de metodologías agénticas 2026.md` and its notes;
the author of this audit did not re-fetch them, so read each as Inferred.

> **Read this first (added 2026-11-12, after the audit).** This audit was measured on the Spanish tree
> (`~/metodologia-de-trabajo`). Every path and sha it cites belongs to that tree, so the citations are kept
> as measured and are not translated. Two things changed since:
>
> 1. **Correction.** The audit calls `github/main` the public tree and counts it as two commits. That ref
>    was stale. The published main is `e79d2f0` (49 commits, this English tree, the same commit the Spanish
>    checkout calls `feat/delegation-context`) [Measured: `git rev-parse origin/main` in
>    `~/work-methodology`; not re-checked against the remote]. So the English tree was ahead, not behind,
>    and finding 1 and row P0 read differently: the work is porting Spanish-only changes here, not renaming
>    the Spanish tree.
> 2. **Decision.** The owner made this English tree the only canonical one. The port is tracked in
>    `odd/tasks/tree-unification.md`. The other findings were measured on the Spanish tree and have not been
>    re-measured here; treat each as Assumed for this tree until it is.

## Verdict

| # | Finding | Severity | Tag |
|---|---|---|---|
| 1 | Two trees, no merge base: this one (Spanish names, 78 commits ahead) and the public `github/main` (English names). Five feature branches hang from the English tree and never reached this one. | Blocks everything else | Measured |
| 2 | "Artifacts in English" holds for content and fails for names: 14 of 17 skills, 3 of 11 roles, 7 of 8 principle files, `METODO_*`, and the change card's canonical keys. | High | Measured |
| 3 | With the shipped `rdd.mode: "warn"`, four behaviours block and the rest write a ledger line. Eight stated rules have no mechanism at all. | High | Measured |
| 4 | The benchmark instrument is real; the proof is one PR, one repetition, one same-family judge. Phase 2 (seeded defects, intervals) is written and has zero runs. | High | Measured |
| 5 | Claude Code and pi are wired. Antigravity is done on a branch. Codex and Gemini are a spec in a JSON file. | Medium | Measured |
| 6 | Memory was write-only: two call sites save, nothing read back, no role or skill mentions memory. | Medium | Measured |

## What this branch already changed

| Change | Where | Proof |
|---|---|---|
| Goal rule: every launched agent has one goal, one specific role, a bounded context | `00-principios/metodologia.md` §9, `protocolo-agentes.md` §1 and §7, `enrutado-modelos.md`, `CONTEXT-PACK.md` | commit `0e37d92`; suite 880 tests OK at that commit [Tested] |
| `brief_check.py` (ported from `feat/delegation-context`, extended) and MCP tool `brief_check` | `03-tools/lib/brief_check.py`, `03-tools/mcp/catalog.py` | 23 tests in `tests/test_brief_check.py`, 1 in `tests/test_mcp_server.py` [Tested] |
| Launch gate `guard_spawn.py` on `Task\|Agent` for Claude Code and the pi matrix | `03-tools/hooks/` | 11 tests in `tests/test_hooks.py` [Tested]; an independent verifier ran 36 synthetic inputs and found four defects in the checker, the MCP tool and the bridge, all fixed test-first; no live run on either runtime [Unknown] |
| Memory is read back by reference (`engram_bridge.py --recall`, three pointers at session start) and the rule says who reads and who writes | `03-tools/lib/engram_bridge.py`, `hooks/session_start_status.py`, `adaptadores-de-runtime.md` §5 | commit `1df6365`; 5 tests [Tested]; one real recall returned two pointers from the owner's store [Measured] |
| The docs lint follows its own checkout: the caps file named `~/metodologia-de-trabajo`, so from a worktree or a clone the documented command checked another tree and reported clean | `03-tools/lib/docs_lint.py`, `config/docs-caps.json` | commit `a0f10f7`; 3 tests [Tested] |
| English wording in roles, skills, the card template and schema comments; a test fails on Spanish labels there | `01-roles/agents/`, `03-tools/config/ficha-de-cambio.template.md`, `tests/test_english_artifacts.py` | commit `d477636`; 5 tests [Tested] |

## 1. Structure: two trees

`git merge-base HEAD github/main` prints nothing [Measured]. `github/main` has `00-principles`, `04-templates`,
`05-adopt`, `06-languages`, `07-communication` and a `docs/` folder; this tree has the Spanish names [Measured:
`git ls-tree --name-only github/main`].

| Branch (English tree) | Ahead | Holds | In this tree? |
|---|---|---|---|
| `feat/delegation-context` | 49 | `brief_check.py`, done-gate hook, tool-output filter, metrics M100-M107, activation profiles | only `brief_check.py`, ported here |
| `feat/harness-guides` | 31 | `docs/08-harnesses.md` for Codex, Antigravity, OpenCode, local models | no |
| `feat/router`, `feat/model-router` | 12, 5 | deterministic model and effort router, `router_eval.py` | no |
| `feat/kit-direction` | 30 | October audit and research dossiers | no |
| `feat/agy-adapter` (this tree) | 10 | Antigravity adapter: render target, hook bridge, installer, doctor | fast-forward away |

Two of them disagree: `feat/harness-guides` says Antigravity hooks are unavailable, `feat/agy-adapter` bridges
them on agy 1.4.7 [Measured by the mapper, both read with `git show`]. Until one tree is canonical, every
feature lands twice or not at all, and a team cannot tell which kit it is installing.

## 2. Language drift

| Layer | Spanish left | References that break on rename | Risk of renaming |
|---|---|---|---|
| Directories (`00-principios`, `04-plantillas`, `05-adaptar`, `06-lenguajes`, `07-comunicacion`, `ejemplos`) | 6 | 163 path strings; `kit_status.py:66`, `init_kit.py:315` hardcode them | medium, scripted |
| Principle and template files | 7 of 8, 4 of 6 | docs and `docs-caps.json` | low |
| Skills | 14 of 17 (`revision-con-recibo`, `ficha-de-cambio`, ...) | 3 to 18 each | medium: installed in target repos |
| Roles | `confrontador` (102), `verificador` (61), `adversario-puntos-ciegos` (28) | `mcp/catalog.py:213`, receipts, benchmark JSON | medium |
| `METODO_*` (12 variables), `metodo-hook` marker | about 240 and 74 hits | installed hooks, user shells, uninstall detection | highest |
| Change card keys | canonical `"Por qué"`, `"Para qué"`, ...; English only as alias (`schemas/change-card.schema.json:6-40`) | 106 hits, `rdd_risk.py:163` | medium: flip canonical and alias |
| Epistemic tags, verdicts and states in role wording | `Medido` 119, `Probado` 82, `Inferido` 50 against `Measured` 2608; roles told agents to emit `ROTO`, `ABIERTO` | `output_lint.py:44` accepts both | fixed in `d477636` |
| Schema comments, card template | nine `_comment` fields, `ficha-de-cambio.template.md` | target repos get the template | fixed in `d477636` |
| Lens ids, property names | `flujo-critico`, `jamas-peor-que-antes`; `Dinero`, `Estado del pago` in `config/project.json:26-33` | config in target repos | medium |

Intentional Spanish, to keep: `07-comunicacion/identidad.es.md`, the Spanish reply locale in `output_lint.py`
and `review_comment_post.py`, and the owner's verbatim quotes in `odd/tasks/` [Inferred].

All counts are Measured by `rg -c` over tracked files. The public tree already uses the English names, so
the rename is also the convergence step of section 1: do it once, by script, with the old names kept as
aliases for one release (`METODO_*` read as a fallback, old skill names as thin redirects).

## 3. Adherence: what a rule does when an agent ignores it

| Strength | Rules |
|---|---|
| Blocks | subagent push, PR, merge, tag; subagent edits to shared build files; force push; tool-call budget; a written round JSON without tags; receipt approval without its required roles; doc caps for the 39 listed files |
| Warns (ledger only, default mode) | main-session push without a receipt; a write outside `may_write`; an invalid subagent answer; reply lint; a launch without a goal contract (new) |
| Prose only | the six questions; cartographer first; every commit green; benchmark per release; token caps (`max_context_tokens` is copied, never measured); judge escalation; English artifacts beyond labels; no AI attribution |

All rows are Measured at `fc3f968` by the adherence mapper, with `path:line` per rule in its report.

Three facts matter more than the table:

- A subagent with no kit contract gets no budget and no write allowlist (`hooks/budget.py:26`,
  `hooks/_common.py:138-152`), so a non-kit agent runs less constrained than a kit role. The new launch gate
  closes the door on the way in; the budget default is still open.
- An approved receipt lets the main session push silently (`hooks/guard_gates.py:140-142`), while the law
  says approval never pushes (`CONTEXT-PACK.md:90`).
- All hooks fail open by design (`hooks/_common.py:215-224`). That is defensible, and it should be written
  in the adoption page so a team knows a crashed hook is a silent pass.

Contradictions to fix in one pass: judge tier (`CONTEXT-PACK.md:61` large, 60k; contract sonnet, 30k);
`may_write` "empty except proposer and mechanic" against nine contracts with round globs; "five hooks" in
prose against eight measured; reply lint "moves to block" (`recibo-de-revision.md:48-50`) against "never
blocks" (`hooks/reply_lint.py:3`). A fifth, `docs_root` hard-coded to `~/metodologia-de-trabajo`
(`config/docs-caps.json:40`), is fixed in `a0f10f7`.

Dead weight to delete: `lib/test_test_sectors.py` (279 lines, not discovered by the suite),
`config/model-tiers.json` (no code reader), `config/examples/generic-proposer.contract.json` (150k tokens
against 60k in the real contract), `lib/bench_output_lint.py` (only its own test uses it), and the same
600-character history comment pasted in nine contracts [Measured].

## 4. Benchmarks

| Benchmark | Sample | Verdict | Why |
|---|---|---|---|
| Phase 1 retrospective | 76 sessions, one owner, one repo | Suggestive for usage, Unsupported for cause | model, effort and task mix drift; no control |
| PR 176 pilot | 1 PR | Unsupported | the kit arm never ran the kit |
| Cell 176b | 1 PR, 1 repetition | Suggestive | 7 valid findings against 6; only the 6.3x cost ratio is solid |
| Field report | 3 rounds | Suggestive | the kit's own judge, no ground truth |
| Communication bench | 15 per arm | Suggestive for conformance | the kit's lint scores the arm told to follow that lint |
| Cold trial (`README.md:64-66`) | 1 | Unsupported | no artifact in the repo; the claim is tagged Measured |
| Phase 2 protocol | 0 runs | Unsupported until run | the design is sound: four arms, seeded defects, decoys, intervals |

Verdicts are Inferred from the files the benchmark mapper cites at `fc3f968`.

What a team of 5 to 20 cannot do today [Measured]: measure an outcome against ground truth (no seeded tasks);
get an interval (`rg -i 'bootstrap|confidence|pass\^k'` finds nothing in the benchmark code); run more than
one PR, one repetition and one judge (`08-benchmark/protocols/pr-review-ab.md:58`); aggregate more than one
engineer (`03-tools/lib/bench.py:60` reads one user's transcripts); measure any runtime but Claude Code.
One bug: `pr-review-ab.sh:161` builds the transcript path with a slash-only substitution while `bench.py:67`
maps every non-alphanumeric character, so on a repo path with `_` or `.` the evidence gate drops to a warning
and the judge still runs [Inferred from the code, not executed].

The kit's own law asks for "single-variable arms" (`CONTEXT-PACK.md:50-51`); its own A/B changes hooks,
skills, agents, MCP, memory and the prompt together. Either run module-by-module arms or state that the
benchmark measures the bundle.

## 5. Runtimes

| Runtime | Entry file | Roles | Skills | Hooks | MCP | Installer and doctor |
|---|---|---|---|---|---|---|
| Claude Code | `CLAUDE.md` importing `AGENTS.md` | yes | yes | yes | yes | yes |
| pi | `AGENTS.md` | yes | yes | yes, proven with a fake pi API only | yes | yes |
| Antigravity | plugin `rules/AGENTS.md` | branch | branch | branch | branch | branch (`feat/agy-adapter`) |
| Codex | none | spec only (`config/model-tiers.json:216-231`) | no | no | no | no |
| Gemini CLI | none | spec only (`model-tiers.json:198-214`) | no | no | no | no |

The market moved in the kit's favour during 2026 (source: `runtimes_portabilidad.md`):

- `AGENTS.md` is read by all five. Claude Code reads it natively when no `CLAUDE.md` exists above it. Keep
  it under Antigravity's 24,000 bytes per file and Codex's 32 KiB chain; the kit's 48-line `AGENTS.md` fits.
- All five implement Agent Skills, and four read `.agents/skills/`. Claude Code documents only
  `.claude/skills/`. One render target plus one copy covers everything.
- All five have a pre-tool hook that can block. Codex mirrors Claude Code's hook shapes, so the kit's Python
  hooks should run there with a thin config. Antigravity has six events. Hooks are a hard boundary nowhere:
  Codex says so, `claude --bare` skips them.
- Gemini CLI was replaced by Antigravity CLI for the unpaid tier on 2026-06-18. Antigravity covers the
  Gemini models; a separate Gemini CLI adapter is the lowest priority.
- Subagent definitions stay incompatible (Markdown with different frontmatter; TOML on Codex; none on pi).
  `render_agents.py` is the right design: one source, one renderer per runtime.

What "keeps the pace" on every runtime is the part that needs no hook: `AGENTS.md`, the context pack, the
goal contract, and the MCP tools (`brief_check`, `change_card_validate`, `receipt_*`). Where a hook is
missing, state per runtime which rules degrade to prose; today only pi has that table
(`adaptadores-de-runtime.md:30-47`).

## 6. Multi-agent work and memory

**The goal rule and its evidence** (source: `orquestacion_multiagente.md`). In the MAST failure taxonomy
(arXiv 2503.13657), specification problems are 41.8% of multi-agent failures; not knowing the termination
condition alone is 9.8%. A verification step adds 15.6 points of task success. That backs one explicit goal,
a stop condition and an acceptance check. Two cautions:

- Multi-agent helps on parallel work (+80.9%) and hurts on sequential work (-39% to -70%), mean -3.5% over
  180 configurations (arXiv 2512.08296). The rule says how to launch an agent, not that launching one is good.
- "Never a general-purpose agent" is stricter than any vendor: Claude Code and Codex ship a general-purpose
  subagent, and job-title roles are 0.5% of failures. What the evidence supports is "never a general-purpose
  brief". The checker follows that: a general-purpose `subagent_type` passes when the brief names one
  specific role with its model; a general-purpose `ROLE` never passes.

**Memory** (source: `memoria_agentes.md`). On VibeMemBench (arXiv 2609.23570) four memory systems failed to
beat memory-off in 11 of 12 pairings; a short verified record helped by 1.1 to 4.5 points, and irrelevant
memory cost up to 3.4. The failure was the form of what got injected, not the ranking. So the kit's rule is
to read memory back by reference and in small pieces, and to write only what was verified:

| Who | Reads | Writes |
|---|---|---|
| Orchestrator | `mem_context` once per session; `mem_search` scoped to the feature before each launch | decisions and verified learnings, one topic key per thing |
| Worker | only the `engram:<topic-key>` references its brief lists in `INPUTS` | nothing; it returns `learnings` in its output |
| Scripts | `engram_bridge.py --recall` at session start: ids and titles, never bodies | receipts and handoffs (unchanged) |

The installed engram is 3.4.0 and 3.7.1 is out [Measured: `engram --help`, 2026-11-12]. The kit's own
numbers say 373 of 405 sessions saved nothing and recall median was 0 (`reports/Benchmark de metodologías
para agentes.md:56`), and the metric that would show whether this changes (recall-used rate, M104) is on the
unmerged `feat/delegation-context`.

## 7. Market position

| Where the kit stands | Items | Basis |
|---|---|---|
| Rare or unclaimed | per-claim epistemic tags with a citation checker; "cite the statement, not the comment"; determinism and negative-control tests on its own scripts; a self-benchmark with a vanilla arm, an arm-validity gate and published unsupported verdicts | no surveyed framework ships them (`frameworks_metodologia.md`); absence is read from READMEs, not from a full audit [Inferred] |
| Already claimed by someone | frozen-candidate receipts, risk-tiered review, dual adversarial review, a published loss: Gentle AI has all four, and the kit's ODD and RDD derive from it | compare against Gentle AI, do not claim novelty |
| Commodity | spec before code, task lists, a rules file, review gates, a fast path for small work | Spec Kit, OpenSpec 2.0, BMAD V7 all ship them |
| Leaders do it better | distribution (skills and plugin marketplaces: 317 plugins in Claude Code's official one; Spec Kit presets and private catalogs); team policy (managed settings, SSO); with/without-skill evals (Tessl); a human-approval inbox for learned memory (Gemini CLI) | adopt |

Adoption signals on 2026-11-12, GitHub stars: Superpowers 316.5k, Spec Kit 149.5k, OpenSpec 74.7k, BMAD
55.3k, Gentle AI 8.8k. Evidence that any of them improves outcomes is thin: one vendor-run benchmark of 50
tickets shows 72% merged without specs against 80-84% with, inside a ±10 point noise band; the one controlled
study of instruction files found no gain and over 20% more cost (arXiv 2602.11988). Nobody ships outcome
metrics. That is the opening: the kit's honest measurement is what the market lacks, and it is also the part
the kit has not finished.

## 8. For a team: adopt in steps, measure against a baseline

| Step | When | What the team does | Exit check |
|---|---|---|---|
| 0. Rules only | day 1 | `AGENTS.md`, the context pack, evidence tags, the change card. No tooling. | every PR carries a card |
| 1. Wired, warn mode | week 1 | `init.sh <repo>`; doctor and smoke pass; hooks only ledger | `bench.sh status` shows sessions measured |
| 2. Calibrate | weeks 2-3 | read the ledger; mark false positives; fix the config | each hook's false-positive rate is known |
| 3. Block what earned it | week 4 | set `hook_modes` to `block` hook by hook, launch gate included | no hook blocks above the agreed false-positive rate |
| 4. Full loop on critical paths | month 2 | receipts at medium and high, the two-adversary round, benchmark per release | receipts exist for every critical-path merge |

How to know whether it is good (source: `medicion_equipos.md`; sample sizes there are the researcher's
calculations, not published thresholds):

- Compare methodology A against B, both with agents. A no-AI arm is no longer runnable: METR reports
  developers refuse it.
- Headline metrics: activation (did hooks, roles and MCP tools fire), seeded-defect recall by severity with
  the false-finding rate, cost per merged PR, rework and escaped defects, gate precision, human
  interventions per task.
- Repeat each cell at least three times, analyse paired, report bootstrap intervals. Single-run agent scores
  move 2.2 to 6 points at temperature 0, so a 3-point difference from one run is noise.
- Frame success as non-inferiority and cost as the price of the recall gained. Judges from two model
  families, order swapped, deterministic checks first. Write the plan before the run and publish the losses.

Missing for this today: the statistics code, seeded tasks, a runner over many PRs, a second judge family,
per-engineer aggregation and a one-page runbook (section 4).

## 9. Order of work

| Priority | Work | Decision the owner makes |
|---|---|---|
| P0 | Make one tree canonical: rename this tree to the English names by script, keep aliases one release, then port `feat/delegation-context`, fast-forward `feat/agy-adapter`, port the router and the harness guide, and publish | which tree is canonical; when the public repo is replaced |
| P1 | Adherence: owner gates absolute in the main session; a default budget for agents without a contract; `validate_subagent_output` and `guard_spawn` to `block` after one calibration week; a real role-contract schema with a test; the contradictions and dead weight of section 3 | which hooks block by default |
| P2 | Runtimes: installer writes `AGENTS.md` and `.agents/skills/`; `install-codex.sh` reusing the Python hooks; one degradation table per runtime; a doctor check per runtime | whether Gemini CLI is dropped in favour of Antigravity |
| P3 | Evidence: run Phase 2 on a public repo; add intervals and repetitions; fix the evidence-gate path; back or remove the cold-trial claim; write the team runbook | budget for the runs (the protocol forecasts USD 550-880) |
| P4 | Memory: port the recall-used metric; upgrade engram; decide on an approval inbox for learned memory | none |

## Not covered

No benchmark or model run was executed for this audit. The pi extension, the launch gate and the Antigravity
adapter were not run on a live runtime. `06-lenguajes`, `07-comunicacion` and `08-benchmark` prose was read
by search hits, not line by line. The owner's personal files were not opened. The earlier claim of a
"ReviewBench" benchmark (October notes) could not be found again by this round's research; treat it as
Unknown until re-sourced.
