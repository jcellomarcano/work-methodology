# C6 · Whole-kit text audit for context (S6)

Measured at HEAD `44bd74c` (working tree dirty: 16 paths from parallel workers; of the measured texts only
`00-principles/model-routing.md` was modified, measured as found). Every number below comes from
`$TMPDIR/c6audit/{audit,trim}.json` or a pasted command (method in §8). **Tokens = `ceil(chars / 4)`**, an
[Inferred] estimate for ratios and caps, not a tokenizer; bytes, lines and words are [Measured].

## 1. Load modes (what a Claude Code session actually gets)

- **Always (main session):** `CLAUDE.md` + the `@AGENTS.md` import, the SessionStart hook output, the `metodo`
  MCP `tools/list` (all 31 tools, assuming no deferred loading [Assumed]), the skill index
  (`name: description` of 16 skills) and the subagent index (`name: description` of 11 `generic-*` roles).
- **Per subagent launch:** the Claude body (frontmatter stripped) plus the JSON schemas of the MCP tools in its
  `tools:`; on pi, the rendered file (`render_agents.py --target pi`) instead of the body. References a role
  may read: its contract, `04-templates/brief.md`, `round-context-pack.md`, `CONTEXT-PACK.md` (protocol §5).
- **On demand:** skill bodies, `00-principles/*`, `06-languages/*`, `docs/*`, `README.md`, `07-communication/*`.
  Never installed: the identity adapter (`07-communication/adapters/*`; `grep -rln "identity.en\|identidad\|
  07-communication" 03-tools/bin` → no match) [Measured]. Hook messages: only what hooks print to the model.

## 2. Totals per load mode [Measured sizes; tokens Inferred]

| Mode | Items | Bytes | Lines | Words | Tokens |
|---|---|---|---|---|---|
| always (main session) | 6 | 23,890 | 88 | 1,973 | **5,974** |
| per-subagent, Claude bodies (11) | 11 | 34,741 | 494 | 4,929 | 8,689 |
| per-subagent, pi renders (11) | 11 | 48,881 | 781 | 6,886 | 12,223 |
| per-subagent refs (11 contracts + brief, agent-brief, round-context-pack, CONTEXT-PACK) | 15 | 24,130 | 481 | 3,137 | 6,030 |
| on-demand | 52 | 271,458 | 3,866 | 40,312 | 67,803 |
| hook messages (one firing of each of 8 sites) | 8 | 1,898 | 8 | n/a | 477 |

Always-loaded breakdown (tokens): MCP `tools/list` 3,366 (56%) · skill index 1,306 · `AGENTS.md` 739 ·
subagent index 460 · SessionStart output 66 (4 lines on a fixture; code caps it at 10 lines) · `CLAUDE.md` 37.
MCP split: descriptions 712, input schemas 2,221, zero property-level descriptions; `route` alone is 393
(33 + 360). 15 of 31 tools declare no role, i.e. orchestrator-only, yet all 31 load in the main session.

Agent that obeys `AGENTS.md` "Read first" (CONTEXT-PACK, then README): 5,974 + 1,738 + 4,860 = **12,572**.

Per subagent launch, Claude (body + MCP schemas of its tools), tokens [Measured sizes]:

| Role | Body | MCP schemas (tools) | Body+MCP | pi render | + CONTEXT-PACK, round pack, brief (§5) |
|---|---|---|---|---|---|
| generic-proposer | 838 | 1,003 (8) | 1,841 | 1,217 | 4,266 |
| generic-comment-gate | 1,376 | 455 (2) | 1,831 | 1,689 | 4,256 |
| generic-verifier | 725 | 1,089 (8) | 1,814 | 1,086 | 4,239 |
| generic-mechanic | 594 | 836 (6) | 1,430 | 927 | 3,855 |
| generic-judge | 862 | 534 (3) | 1,396 | 1,178 | 3,821 |
| generic-cartographer | 724 | 724 (6) | 1,448 | 1,075 | 3,873 |
| generic-challenger | 799 | 455 (2) | 1,254 | 1,108 | 3,679 |
| generic-blind-spot-adversary | 788 | 455 (2) | 1,243 | 1,107 | 3,668 |
| generic-boundary-reviewer | 717 | 263 (2) | 980 | 1,001 | 3,405 |
| generic-human-reviewer | 723 | 205 (1) | 928 | 1,015 | 3,353 |
| generic-style-reviewer | 543 | 205 (1) | 748 | 820 | 3,173 |

The pi render adds 3,534 tokens over the 11 bodies (+41%), 2,527 of them in the rendered contract section.
All roles sit far below `max_context_tokens` (15k–60k): subagent context goes to file reading (`model-routing.md`).

## 3. Top 10 items by tokens (all modes; on-demand unless marked)

1. `README.md` 4,860 (301 lines; 2nd in AGENTS "Read first") · 2. `00-principles/methodology.md` 3,949 (216) ·
3. `06-languages/gradle.md` 3,892 (148) · 4. MCP `tools/list` 3,366, **always** · 5. `concurrency-kotlin.md`
2,854 (130) · 6. `go.md` 2,782 (150) · 7. `python.md` 2,620 (118) · 8. `sql.md` 2,564 (114) ·
9. `concurrency-swift.md` 2,414 (120) · 10. `haskell.md` 2,193 (107).

Largest per-subagent: comment-gate body 1,376; largest skill bodies: `init-kit` 1,232, `receipt-review` 1,013.
On-demand by group: 06-languages 26,497 (11) · 00-principles 12,745 (8) · skills 8,421 (16) · 07-communication
6,690 (5) · README 4,860 · docs 4,732 (7).

## 4. Duplication (5-word shingles, Jaccard on normalized sentences ≥ 8 words)

Components with Jaccard ≥ 0.5 across ≥ 2 files: **23**, redundant tokens **1,706** (sum per component minus
its largest copy). The top six are agent-body boilerplate and hold 1,350 of them (79%):

| Redundant tok | Files | Passage (normalized) |
|---|---|---|
| 297 | 10 bodies | "never touch settings.gradle, build.gradle, gradle.properties, gradle/libs.versions.toml, app/build.gradle or .claude/**" |
| 260 | 11 bodies | "Budget: max_tool_calls comes from your contract and the harness denies the next call…" |
| 230 | 11 bodies | "When that happens, stop and emit your JSON with truncated: true and not_covered; never push on." |
| 223 | 8 bodies | "Write your document with output_write (schema X; FAIL writes nothing); hand off with handoff_write" |
| 190 | 7 bodies | "`../../03-tools/schemas/X.schema.json` (moved out of this body so output_write … can validate it)" |
| 150 | 11 bodies | "Never talk to the user directly; never spawn other agents." |
| 68 | kotlin.md, swift.md | concurrency house-rules sentence |
| 30 | methodology.md, CONTEXT-PACK.md | third-party SDK defect / retirement condition |

Cross-document near-duplicates (Jaccard ≥ 0.3, agent-body pairs excluded): 37 sentence pairs; in the top 25,
`methodology.md`↔`CONTEXT-PACK.md` 7, `methodology.md`↔`docs/01-principles.md` 3, `model-routing.md`↔
`CONTEXT-PACK.md` 2, `methodology.md`↔`why-layer.md` 2. These are summaries by design (CONTEXT-PACK §2 is
"summary of methodology.md"); they cost only when an agent loads both, so they are not a trim priority.
On pi the budget/output/handoff/delivery rules appear twice in the same file: once in the body, once in the
rendered contract section (`render_agents.py` `contract_section`).

## 5. Fitness for context

**Spanish leftovers in model-facing English text** (`grep -n "Medido\|Desconocido\|Inferido"`, [Measured]):
- `generic-verifier.md:15` "You are the **Verificador**"; also in its pi render.
- Epistemic tags in Spanish while CONTEXT-PACK/AGENTS use English: `generic-cartographer.md:47`
  (`{Medido, Probado, Inferido, Asumido, Desconocido}`), `generic-challenger.md:49`, `generic-judge.md:49`,
  `generic-blind-spot-adversary.md:47`, `generic-human-reviewer.md:41,53`, `04-templates/brief.md:14`,
  `02-skills/necessary-comment/SKILL.md:38`, `07-communication/identity.en.md:35`, MCP `shape_metrics`
  description ("labelled Inferido"). Schemas accept both languages (`grep -l Desconocido
  03-tools/schemas/*.json` → 9 files), so this is a consistency defect, not a validation bug. Intentional bilingual markers in `07-communication/templates.md`/`rules.md` are excluded.
- Never-installed `07-communication/adapters/CLAUDE.md` imports `identidad.es.md` (Spanish, 1,491 tok).

**Project-specific text in generic roles.** 10 of 11 bodies hard-code a Gradle/Android build-file list; the
real list is `config/project.json: shared_build_files`, enforced by `guard_paths.py` for Edit/Write/MultiEdit.
`generic-proposer.md` (5) and `generic-verifier.md` (2) mention Gradle. "generic v3 loop" appears in all 11
bodies (12 times) and is defined nowhere in CONTEXT-PACK, agent-protocol or brief (`grep v3` → no match).

**Rules a hook already enforces, repeated in every body** (tokens over the 11 bodies, from `trim.json`):
budget paragraph 572 (`budget.py:39` denies at the cap with the same instruction, independent of RDD);
build-file list 380 (`guard_paths.py:31`, independent of RDD, but blind to `Bash`, which proposer and verifier
have); never-talk/spawn 165 (subagents have no Task tool in `tools:`; delivery denied by `guard_gates.py:120`);
"moved out of this body" output pointers 232 (`validate_subagent_output.py:75` blocks invalid JSON).

**Instructions an agent cannot act on.**
- 23 `../../…` pointers in the 11 bodies (`../../00-principles/agent-protocol.md`, `../../03-tools/schemas/…`).
  Neither `render_agents.py` nor `install-claude.sh` rewrites them (`grep '\.\./\.\.'` → no match), so in
  `<repo>/.claude/agents/` they resolve to `<repo>/00-principles/…`, absent in a target repo [Inferred].
- `agent-protocol.md` §5 says the cold-start pack includes `CONTEXT-PACK.md`, but no body, skill or template
  delivers it (`grep -rn CONTEXT-PACK 01-roles 02-skills 04-templates` → only init-kit's scaffold list)
  [Measured]. Either wire a small subagent core or correct §5.
- "moved out of this body so output_write and the harness can validate it": history, not an instruction.

**Stale references.** Backticked `*.md|json|py|sh|ts` refs checked against the kit tree: 56 runtime
artifacts (round files, `out/`, `.mcp.json`, target `CONVENTIONS.md`) skipped; 44 unresolved by literal path,
of which 40 are bare basenames of tracked files (e.g. `init.sh` for `03-tools/bin/init.sh`: findable, but an
agent must search). The 4 with no tracked basename are declared pending or external, not dead:
`install-gemini.sh`/`install-codex.sh` ("pending"), `docs/architecture/organic-rdd.md` (gentle-ai's repo),
`output-lint.personal.json` (git-ignored by design). Hook text cites `methodology.md` paragraphs 4 and 6;
both exist (§4 owner gates, §6 Git) [Measured].

**Over useful length.** `AGENTS.md` sends every entering agent to the whole `README.md` (4,860 tok, written
for people) when it names only "the kit map and the measured status block" (README lines 89–100: 237 tok).
`AGENTS.md` "Plug, check, unplug" (228 tok) is target-repo procedure inside the kit-dev entry point; CONTEXT-
PACK §6 covers it. 13 of 16 skill descriptions exceed 60 tokens (max `init-kit` 109, `review-comment` 108).
Hook messages are fit: 38–74 tok per firing; worst case `validate_subagent_output.py:75` can append up to 800
chars of errors (`[:800]`), ~230 tok [Inferred]. `reply_lint.py` and `touched_paths.py` print nothing.

**Uncapped model-facing texts.** `docs-caps.json` caps 31 docs by lines only; agent bodies, skills,
templates, contracts, `docs/*` and `03-tools/README.md` have no cap (25 model-facing items in `uncapped`).
Its `docs_root` is `~/work-methodology`, so the AGENTS.md command lints that checkout, not the worktree.

## 6. Trim plan, ordered by saving (tokens, from the script; replacements are estimates)

| # | File(s) | Action | Saving |
|---|---|---|---|
| 1 | `AGENTS.md` "Read first" #2 | point to README lines 89–100 (status block) + "Repository map", not all of README | ~4,623 per obedient session start [Inferred] |
| 2 | 11 `generic-*.md` | cut the 4 boilerplate blocks of §5 (budget para, Gradle list, Gradle concurrency line, "moved out" pointer, never-talk) to one generic line (below) | 1,472 gross over 11 bodies; avg 134, max 218 (proposer) per launch |
| 3 | pi render | after #2 the rendered contract section is the single source: no double budget/output/handoff | the #2 lines again on pi (budget + pointers 804 over 11) |
| 4 | 16 skill descriptions | cap 60 tokens (cap 50) | 311 (451) per session |
| 5 | `AGENTS.md` "Plug, check, unplug" | move to CONTEXT-PACK §6 / README "Start here" | 228 per session |
| 6 | `CONTEXT-PACK.md` | if §5 is wired: give subagents only the head + §4 (62 + 174 = 236), not 1,738 | avoids up to 1,502 per launch vs wiring the whole pack |
| 7 | MCP `tools/list` | descriptions are already short (cap 30 saves 5); real lever is harness-side deferred tool loading or a slimmer `route` schema | not estimated [Unknown] |
| 8 | bodies, brief, skill, identity, MCP | Spanish tags → English; "Verificador" → "Verifier"; define or drop "v3" | ~0; consistency |
| 9 | 11 bodies | rewrite `../../` pointers to tool names (`output_write` schema name) or `${METODO_TOOLS}` paths | ~0; makes pointers actionable |

Replacement line for #2 (one per body, 137 chars = 35 tok): "Never edit shared build files or `.claude/**`
(any tool, including Bash); on a budget deny, emit JSON with `truncated` and `not_covered`."
Net of #2 with that line: 1,472 − 11 × 35 = 1,087 over 11 bodies (~99 per launch).

**Do not cut** (no hook covers them): IRON LAW lines and role-specific prohibitions (adversary never proposes
the fix; verifier never accepts claimed results), which define the role; the evidence rule (statement, not
comment), checked only after the fact by `cite_check.py`; the `output_write`/`handoff_write` call with its
schema name; the generic build-file/`.claude` rule (`guard_paths.py` sees Edit/Write/MultiEdit, not Bash, and
hooks can be uninstalled); `AGENTS.md` personal-files and owner-gate rules; the hook deny texts themselves.

## 7. Deterministic budget proposal (design only)

Caps in tokens (`ceil(chars/4)`), each with today's measured value:

| Target | Cap | Now |
|---|---|---|
| `AGENTS.md` | 600 | 739 |
| `CLAUDE.md` | 60 | 37 |
| SessionStart output (by test on a fixture) | 120 | 66 |
| each skill `description` / total skill index | 60 / 1,000 | max 109 / 1,306 |
| each agent `description` / subagent index | 45 / 500 | 460 total |
| each Claude agent body | 800 | max 1,376 (3 over: comment-gate, judge 862, proposer 838) |
| each pi render | body + 250 | +277 to +379 |
| each skill body | 1,000 | max 1,232 (2 over) |
| `CONTEXT-PACK.md` / subagent core | 1,800 / 400 | 1,738 / n.a. |
| `04-templates/brief.md` | 300 | 267 |
| MCP `tools/list` total / per tool (unit test on `catalog.TOOLS`) | 3,500 / 400 | 3,366 / 393 (`route`) |
| each hook message (unit test per emit site) | 80 + capped error tail | 38–74 |

`docs_lint` extension: add `"token_caps": {"AGENTS.md": 600, …}` and `"field_caps": [{"glob":
"02-skills/*/SKILL.md", "field": "description", "cap": 60}, {"glob": "01-roles/agents/generic-*.md", "part":
"body", "cap": 800}]` to `docs-caps.json`; same `offenders/missing/ok` report, sorted, no timestamps, method
string `ceil(chars/4)` in the output; frontmatter split as `render_agents.split_frontmatter`; `docs_root`
defaulting to the repo being linted. MCP and hook caps live as unit tests because their text is code.
Negative control: one fixture over each cap must fail.

## 8. Measurement method (re-run)

Scripts and outputs in `$TMPDIR/c6audit/` (outside the repo, not deleted): `audit.py`, `trim.py`,
`audit.json`, `trim.json`, `session_start.out`, `project.json`, `fixture/` (empty git repo), `hooks/`.

```
D=$TMPDIR/c6audit; K=<kit root>
git -C $D/fixture init -q && git -C $D/fixture -c user.email=a@b -c user.name=a commit -q --allow-empty -m init
echo '{"rdd":{"enabled":true,"mode":"block"}}' > $D/project.json
echo "{\"session_id\":\"s1\",\"cwd\":\"$D/fixture\",\"source\":\"startup\"}" | PYTHONDONTWRITEBYTECODE=1 \
  METODO_PROJECT_CONFIG=$D/project.json METODO_HOOKS_DIR=$D/hooks METODO_RDD_DIR=$D/rdd \
  CLAUDE_PROJECT_DIR=$D/fixture python3 $K/03-tools/hooks/session_start_status.py > $D/session_start.out
python3 $D/audit.py $K > $D/audit.json && PYTHONDONTWRITEBYTECODE=1 python3 $D/trim.py $K > $D/trim.json
```

`audit.py`: inventory by load mode; MCP via `from mcp import catalog` serialized exactly as `server.py
tools_list()` (compact JSON); pi via `render_agents.py --target pi`; hook texts via AST over `emit_pretool` /
`emit_stop_block` arguments filled with sample values (+110/+30 chars JSON envelope [Assumed]); duplication by
5-word shingles on normalized sentences, union-find at Jaccard ≥ 0.5; Spanish by a stop-word/accent regex then
hand-checked with `grep`; refs by backticked path resolution against kit dirs and `git ls-files` basenames.
`trim.py`: per-body regex line costs, description caps, section sizes. Both print sorted JSON.

## 9. Uncertainties

- chars/4 is not a tokenizer (code, JSON, non-English tokenize denser): ratios hold, absolutes may be off by
  tens of percent [Inferred]. Harness prompts and built-in tool schemas are not counted.
- Whether Claude Code defers MCP schemas or indexes skill `triggers:` (full frontmatter 2,345 vs index 1,306)
  is not measured [Unknown]; C1/C3 should confirm. Duplication misses paraphrase below Jaccard 0.3 and table
  rows under 8 words (the routing table shared by CONTEXT-PACK §3 and `model-routing.md`).
