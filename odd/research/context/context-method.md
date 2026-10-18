# C5 · The kit's context method (synthesis, read 2026-10-18)

Synthesis of C1-C4, C6 for `odd/tasks/context-optimization.md` (S1-S6) + the owner's balance requirement (2026-10-18); not implemented.
Keys: **[CE§n]** `context-engineering.md`, **[EN§n]** `engram.md`, **[AC§n]** `activation.md`, **[DG§n]** `done-gate.md`, **[TA§n]**
`text-audit.md` (here), **[RM§n]** `../model-router/routing-method.md`. Dossier tags carry over; own choices are [Inferred]; tokens =
`ceil(chars/4)` [TA§1]. The router picks role, model, effort [RM§1, RM§3]; this method picks what loads, when, and what proves "done".

## 1. Decision summary

1. **Cap the orchestrator's window**: parent peaks 257k-537k vs auto-compact ~967K, median 0 compactions [CE§1]; decay from 32K [CE§2].
2. **One model and effort per main session**: a switch re-reads history uncached; kit cache hit ratio 0.971 [CE§1, CE§3 T6].
3. **Filter tool output, full output to a file**: tens of thousands of tokens to hundreds [CE§3 T10]; masking halved cost [CE§3 T5].
4. **Subagents: goal contract in, ≤ 2,000-token report out, `max_context_tokens` enforced** (no hook reads it) [CE§4 A2, A3, A6].
5. **Trim loaded text**: always-loaded 5,974 tok (MCP 56%); 4,623 avoidable per obedient start; 1,472 boilerplate in 11 bodies [TA§2, §6].
6. **Token caps in `docs_lint`**: 25 model-facing items have no cap [TA§5, TA§7].
7. **Engram reads by rule, parent only**: recall median 0, 373/405 sessions save nothing; writes-only wiring, no subagent tool [EN§3].
8. **Activation is a computed profile** (bare → full); hooks cost 57-89 ms per run, ~1.5-1.9 s per human turn [AC§1, AC§3].
9. **WARN becomes visible and expires**: today an unseen ledger line, 439 reply_lint FAILs with no effect [AC§1, AC§2 p1]; every
   LOG/WARN goes to BLOCK or OFF at precision 0.90 / act rate 0.10 [AC§4].
10. **Done gate**: 17 file-only rules, warn-first [DG§3-4]; checklist 10/10 vs self-check 5/10 [CE§2]; MAST 6.2% + 8.2% [DG§1].
11. **Measure before tuning**: 9 metrics (§8); budgets and modes move only on them [CE§6 #1, AC§4].

## 2. Main-conversation rules

- **Compaction**: `autoCompactWindow` set by `init.sh` to D1 [CE§3 T3]; `/compact <focus: task doc, open S#, next step>` at block end,
  never mid-task [CE§3 T2]; after two failed corrections on one issue, write state down and `/clear` [CE§3 T1, T7]. **Restore**:
  `session_start_status.py` already fires on `compact` [AC§1]; there it prints task doc path, open S#, last receipt id + tree, profile
  and any `done-unproven` line, ≤ 120 tok [CE§6 #3, DG§4, TA§7].
- **No mid-session model/effort switch** in the orchestrator, skill `model:` overrides included [CE§3 T6, RM§3 ladder].
- **Tool output**: a PostToolUse hook (`updatedToolOutput`) keeps failures/matching lines, writes the full output under
  `out/hooks/<session>/tool-out/` and returns its path [CE§3 T10]. **Tools on demand**: CLI first, MCP deferred; `tools/list` is 3,366
  tok, 15 of 31 tools orchestrator-only [TA§2, CE§3 T8, AC§2 p4]; the doctor prints the always-loaded estimate [AC§5].
- **Instruction files, skills**: CLAUDE.md/AGENTS.md < 200 lines and under §7 caps; one level of disclosure; key rules first in
  `SKILL.md` (re-injection keeps ≤ 5,000 tok from the start) [CE§3 T4, T9]; D5, D6 [AC§3, TA§7]. Carry paths + ranges, no re-reads [CE§3 T11].
- **Engram, parent only, start/resume only**, first match [EN§5]: disabled → off; subagent → off; sensitive or project unresolved →
  explicit project, no writes; compacted → `mem_context(compact, 4096)` once; resume → task doc, then that + ≤ 2 `mem_search(limit 5)`;
  multi-session → 1 search; trivial → off; else 1 search only if prior work is named. Never `all_projects`; a recall is a pointer to
  verify in its file; writes only `topic_key` decisions + one handoff; ~1k-tok/turn protocol dropped where reads are off [EN§2, §4, §7].

## 3. Subagent rules

- **Delegate** verbose, self-contained or read-only-breadth work; dependent write chains stay in one context [CE§4 A1, RM§1 #6];
  fan-out comes from the router [CE§4 A7, RM§3]. **Brief** = the goal contract of §4; paths, never content [CE§4 A2].
- **Report ≤ 2,000 tok (~8,000 chars) JSON**; overflow to `handoff_write`, report returns path + sha and `truncated: true`; the
  SubagentStop check covers size as well as shape [CE§4 A3, CE§6 #9]. **`max_context_tokens`** enforced by a post-run transcript check
  (over-cap = protocol finding) [CE§4 A6, CE§6 #12]; bodies + schemas are 0.7k-1.8k tok vs caps 15k-60k, so the cap is file reading [TA§2].
- **De-duplicated bodies**: four hook-enforced blocks → one 35-tok line; pi contract section single source; `../../` pointers → tool or
  schema names [TA§5, TA§6 #2, #3, #9]; `omitClaudeMd: true` with a rule-presence test [CE§4 A4].
- **Cold-start core** (D7): CONTEXT-PACK head + §4 (236 tok), not the 1,738-tok pack `agent-protocol.md` §5 names and nothing delivers
  [TA§5, TA§6 #6]. **No Engram** for subagents [EN§5 row 2]; minimal tools [CE§4 A5]; reviewers get a fresh context [CE§4 A8].

## 4. Balance: quality vs context, and goal anchoring

**(1) Goal contract**: seven fields in every brief; a missing one fails the brief check (WU11) [Inferred from CE§4 A2, CE§2 S37].

| Field | Content |
|---|---|
| objective | one verifiable sentence: an observable outcome, not an activity |
| serves | `odd/tasks/<feature>.md#S<n>` by reference; the harness quotes the S# line verbatim from the file, never a paraphrase |
| acceptance | the exact command, test or file check that proves it (feeds DONE-02/09) [DG§3] |
| scope | allowed edit paths and read paths; out-of-scope edits hit `guard_paths` [AC§3] |
| stop | acceptance passes, budget deny, or a blocking unknown → `truncated` + `not_covered` [CE§4 A3, A6] |
| budget | `max_context_tokens`, `max_tool_calls` from role contract and tier (D12) [CE§4 A6, RM§3] |
| already read | paths + line ranges the parent read, one line each on what they hold [CE§4 A2, CE§3 T11] |

**(2) Quality floor before budget ceiling.** Exact references (path:line, sha, command), not summaries, so the subagent reads the
evidence itself [CE§3 T11]; focused prompts beat full ones in all models tested [CE§2 Chroma]. Cap reads by *scope* (fewer paths), never
by truncating evidence in a path [CE§3 T10]. If the budget would cut evidence, split by module (router P2), never enlarge the window
[RM§3 P2, CE§2]; diligence failures raise effort, then tier, never context [RM§3 ladder].

**(3) Goal anchoring across compaction and handoffs.** Focus line at every compaction; SessionStart restores task doc + open S# + last
receipt (§2) [CE§3 T2, T4]. Every report returns `specs: [{id, verdict: met|partial|not_met|not_judged, evidence}]` for each S# in its
brief, so drift is a count, not an impression; DONE-08 reads the same verdicts [DG§3].

**(4) Metrics that show the balance** (§8): per-role peak vs cap, report size vs 2k, re-read ratio, S# coverage per report, rework rate
(P6 proposer reruns ÷ proposer runs) [CE§5, RM§3 P6]. **Budget rule** [Inferred; thresholds Assumed]: per role, window ≥ 20 runs;
*tighten* the cap to p90 peak × 1.2 when p90 < 0.5 × cap, S# coverage = 1.0 and rework does not rise; *loosen* one step only when
over-cap runs coincide with `truncated`, a P2 split or a P6 rerun citing missing context; otherwise hold. Changes by card [AC§4].

**(5) External verification is the quality guarantee.** Codex passed 8/10 in a clean context vs 3/10 at ~300k chars; an external
checklist 10/10 [CE§2]; self-correction degrades without outside feedback [DG§1]. The done gate (§6) and the verifier carry quality [CE§4 A9].

## 5. Activation

Inputs, no LLM: `rdd_on`, `actor`, `tier`, `critical`, `kind`, `phase`, `lang`, `runtime`, `offline`, `kit_repo`, `tool_search`,
`verdict[e]`; `lib/activation.py derive()` caches `profile.json` per edit [AC§3, AC§5]. Rows, first match: P0 `rdd_on = false` → bare ·
P1 `tier = high`, `critical` or `kind = release` → full · P2 medium → standard · P3 low → scripts · P4 exempt → light · P5 unknown → standard.

| Element (OFF · LOG silent · WARN visible · BLOCK) | bare | light | scripts | standard | full |
|---|---|---|---|---|---|
| push/PR gate without receipt (main) | OFF | OFF | WARN | WARN → rule | BLOCK (ask) |
| subagent scope (`guard_paths`) | OFF | OFF | LOG | LOG → rule | BLOCK |
| subagent JSON output + report cap | OFF | OFF | BLOCK once | BLOCK once | BLOCK once |
| done gate Stop hook (D2) | OFF | WARN, exempt subset | WARN | WARN | WARN → BLOCK |
| roles cap (router picks inside) | none | none | mechanic/proposer | + challenger, verifier | + adversary, judge, boundary |
| comment gate | OFF | OFF | script | + agent if new comments | script + agent |
| docs caps (lines + tokens) | OFF | BLOCK at finalize | BLOCK | BLOCK | BLOCK |
| test sectors / verify | OFF | OFF | touched | touched | `full_required` |

`touched_paths`, `session_start_status` ON except bare; `reply_lint` Stop hook OFF everywhere (D3); kit-status drift BLOCK everywhere when `kit_repo`. **Always BLOCK, bare included, owner-only
changes** [AC§3, AC§4]: force push without lease; subagent edits to shared build files or `.claude/`; subagent delivery; the subagent
call budget; `ask` on a main-session build-file edit. Modifiers [AC§3]: subagents skip main-only elements; pi turns subagent-output
BLOCK into LOG; offline drops online cite checks; explore = light until the first edit; no Gradle → sectors OFF; verdicts by card only.

**Visible WARN channel (decision)** [Inferred from AC§1, AC§5, DG§4]: `hook_mode` gains `off` and `visible` [AC§5]. Tool events: allow
plus one `hookSpecificOutput.additionalContext` line `METODO-WARN <kind>: <fix>`, ≤ 80 tok [TA§7]. Stop events: `systemMessage` to the
owner, and the next `session_start_status` lists ≤ 3 unresolved WARN/`done-unproven` lines [DG§4]. LOG stays silent, a measuring phase
only (no act rate) [AC§4]. A test per emit site asserts the model-facing field; per-harness `additionalContext` support is [Unknown].

**Promote/demote** [AC§4]: per element, ≥ 7 days, ≥ 20 fires. OFF on precision < 0.90, override > 0.10, WARN act rate < 0.10, or 0
fires in 2 windows; BLOCK on precision ≥ 0.90, ≤ 2 confirmed FPs (0 for a main deny); LOG/WARN live ≤ 2 windows; changes by card.

## 6. Done gate

`lib/done_check.py` reads files only, returns ordered JSON (`tool_sha`, `tree_sha`, `rules[]` PASS/FLAG/BLOCK/SKIP-with-reason), same
input same bytes; green proof only from `bin/run-check.sh <sector> -- <cmd>` into `runs.jsonl` (Bash payload has no exit code) [DG§3].

| ID | Check | Fail | ID | Check | Fail |
|---|---|---|---|---|---|
| 01 | claim detection (done/green/committed/delivered) | selects | 10 | `Not tested:` names each skip | BLOCK |
| 02 | green run per touched sector, current tree, after last edit | BLOCK | 11 | no unticketed TODO/FIXME | BLOCK |
| 03 | RED before GREEN for behavior | FLAG (BLOCK strict TDD) | 12 | no `NEEDS-COMMENT` | BLOCK |
| 04 | no weakened, deleted or skipped test | BLOCK | 13 | "committed": clean paths, reachable shas | BLOCK |
| 05 | docs caps; new `.md` has a cap | BLOCK/FLAG | 14 | citations exist (`cite_check`) | BLOCK |
| 06 | README status block (kit repo) | BLOCK | 15 | Measured/Tested tag has evidence | FLAG |
| 07 | "delivered": receipt approved or owner ack | BLOCK | 16 | subagent status matches validation | BLOCK |
| 08 | every S# judged (feature claim) | BLOCK | 17 | nothing running, no tmp leftovers | FLAG |
| 09 | card's "How we'll know" ran | FLAG | | exempt skips 02-04, 09; non-kit skips 06; no claim → silent | |

**Where it runs** [DG§4]: Stop hook `done_gate.py` (main), warn-first via the visible channel; in block mode exit 2 once per tree + rule
set, then `stop_hook_active` lets the stop through and logs `done-unproven`. SubagentStop for writers (16, 02, 04, 13); TaskCompleted.
`bin/done-check.sh <repo> --claim done|green|committed|delivered [--reply f] [--session id]` (exit 0 PASS/FLAG, 1 BLOCK, 2 usage); MCP
`mcp__metodo__done_check`; a skill step in `human-reply`, `pr-message` and the writer return contract (missing block = proposed COM-20).
The agent pastes this block verbatim as the first lines of its reply:

```text
DONE-GATE: BLOCK <n> · FLAG <n> · tree <sha7> · tool <sha7>
- DONE-<id> <BLOCK|FLAG> <evidence> · fix: <command or action>
```

**Owner waiver** [DG§4]: `done-check.sh --waive DONE-xx --reason "<text>"`, an owner gate (`ask`) when an agent calls it; ledger
keeps rule, `tree_sha`, reason, user email; dies with the tree; the block shows `WAIVED by <email>: <reason>`. **FP control** [DG§5]:
PASS + BLOCK fixture per rule, determinism; DONE-01 precision ≥ 0.9 on 50 labelled finals; block per rule at ≥ 20 fires, FP ≤ 10%.

## 7. Text trims

| # | Change, ordered by saving [TA§6] | Saving (tok) |
|---|---|---|
| 1 | `AGENTS.md` "Read first" → README status block + map (by heading), not all of README | ~4,623 per obedient start |
| 2 | subagent core = CONTEXT-PACK head + §4, not the whole pack | up to 1,502 per launch |
| 3 | 11 bodies: hook-enforced boilerplate → one line | 1,087 net over 11 (~99 per launch) |
| 4 | pi render: contract section as single source | up to 804 over 11 on pi |
| 5 | skill descriptions cap 60 (or 50) | 311 (451) per session |
| 6 | `AGENTS.md` "Plug, check, unplug" → CONTEXT-PACK §6 | 228 per session |
| 7-9 | MCP deferred or slimmer `route` (393); English tags, "Verifier", define/drop "v3"; `../../` → tool names | Unknown; ~0 |

**Do not cut** [TA§6]: IRON LAW lines and role prohibitions; the evidence rule; the `output_write`/`handoff_write` call with its schema
name; the generic build-file/`.claude` rule (`guard_paths` is blind to Bash); `AGENTS.md` personal-files and owner-gate rules; hook
deny texts. **Token caps for `docs_lint`** [TA§7] (cap / now): AGENTS 600/739 · CLAUDE 60/37 · SessionStart 120/66 · skill description
60, index 1,000 / 109, 1,306 · agent description 45, index 500 / 460 · agent body 800 / 1,376 (3 over) · pi render body+250 · skill
body 1,000 / 1,232 (2 over) · CONTEXT-PACK 1,800/1,738, core 400 · brief 300/267 · MCP 3,500, 400 per tool / 3,366, 393 · hook message
80 + capped tail / 38-74. Design: `token_caps`, `field_caps` (glob + description|body) in `docs-caps.json`, same report, `ceil(chars/4)`,
`render_agents` frontmatter split, `docs_root` = linted repo (today `~/work-methodology`); MCP/hook caps as unit tests; over-cap fixtures fail.

## 8. Metrics

| Metric | Definition | Computed in | Source |
|---|---|---|---|
| per-role peak vs cap | max(input + cache_read + cache_write) per `agent-*.jsonl` ÷ role `max_context_tokens` | `transcript_metrics.py` (extend) | [CE§5] |
| tool-output share | `tool_result` chars by tool ÷ input chars | `transcript_metrics.py` (new) | [CE§5] |
| re-read ratio | Reads of an already-read path+range ÷ Reads, parent↔subagent too | `transcript_metrics.py` (new) | [CE§5] |
| report size | chars answering each Agent call; share > 8,000 | `transcript_metrics.py`; SubagentStop | [CE§5, CE§6 #9] |
| startup load | first-request tokens per session/subagent; static estimate | `transcript_metrics.py`; `doctor.py` | [CE§5, AC§5, TA§2] |
| recall-used rate | recalls whose id/topic/title reappears ÷ recalls; bytes; empty searches | `transcript_metrics.py` (new) | [EN§6] |
| hook latency | wall ms per hook run, with a run counter | `_common.py` ledger, `hooks_report.py` | [AC§1, AC§4] |
| warn act rate | corrective event after WARN/BLOCK-once ÷ fires; precision; override | `hooks_report.py` per element | [AC§4] |
| S# coverage, rework | S# with a verdict ÷ S# in brief; P6 reruns ÷ proposer runs | report JSON + router log | [RM§1 #10, RM§3 P6] |
| kept | compactions, cache hit ratio (+ subagents), model switches; done-gate fires/waivers per rule | existing + `hooks_report.py` | [CE§5, DG§5] |

## 9. Implementation plan (one commit each, smallest first, suite green, README status re-measured per AGENTS.md)

| WU | Change | Touches | Test-first | Risk |
|---|---|---|---|---|
| 1 | English tags, "Verifier", "v3"; AGENTS read-first, move "Plug" | bodies, `brief.md`, `AGENTS.md`, `CONTEXT-PACK.md` | grep test | README drift: point by heading [TA§5-6] |
| 2 | skill description cap, manual-only skills | `02-skills/*/SKILL.md`, `settings_merge.py`, `init.sh` | yes | lower trigger recall [AC§3] |
| 3 | de-dup bodies, pointers, pi single source | `generic-*.md`, `render_agents.py` | yes, do-not-cut test | drop a rule no hook covers [TA§6] |
| 4 | token/field caps, `docs_root` | `lib/docs_lint.py`, `docs-caps.json` | yes, over-cap fixture | red suite if before WU1-3 [TA§7] |
| 5 | visible WARN channel | `hooks/_common.py`, emit sites | yes | noise; harness support [AC§5] |
| 6 | reply_lint per D3 | `hooks.settings.json`, pi `HOOK_MATRIX` | yes | lose COM ledger data [AC§4] |
| 7 | compact restore, window per D1 | `session_start_status.py`, `settings_merge.py` | yes | banner > 120 tok [CE§6 #2-3] |
| 8 | §8 transcript metrics | `08-benchmark/lib/transcript_metrics.py` | yes, fixtures | chars/4 proxy [CE§5] |
| 9 | run counters, latency, element verdicts, expiry | `_common.py`, `hooks_report.py`, `project.json` | yes | hot-path latency [AC§4] |
| 10 | report cap, S# verdicts, max_context check | `validate_subagent_output.py`, schemas | yes | cap drops findings [CE§4 A3, A6] |
| 11 | goal contract, cold-start core, `omitClaudeMd` | brief template, frontmatter, `agent-protocol.md` | yes, brief check | omitted rule [CE§4 A4] |
| 12 | tool-output filter hook | new PostToolUse hook | yes | hides the line that mattered [CE§3 T10] |
| 13 | Engram read rule | rule function, `runtime-adapters.md`, skills | yes, table test | stale or cross-project recall [EN§7] |
| 14 | `activation.py`, `hook_mode`, router profile cap | `lib/`, `_common.py`, `touched_paths.py` | yes, determinism | wrong profile turns guards off [AC§5] |
| 15-16 | `run-check.sh` + `runs.jsonl`; `done_check.py`, CLI, MCP (two commits) | `bin/`, `lib/`, `config/done-gate.json`, MCP catalog | yes, 17×2 fixtures | unrecorded runs; DONE-01 precision [DG§3, DG§5] |
| 17 | done-gate hooks, waiver, skill steps, COM-20 | `hooks/done_gate.py`, `guard_gates.py`, `output_lint.py` | yes | Stop loop; false negatives [DG§4-5] |

## 10. Open decisions for the owner

1. **Orchestrator auto-compact window**: (a) default ~967K, (b) 500k, (c) 300k, (d) 200k. Rec (c) [Assumed]: under the 373k
   multi-agent median peak, over the 257k single median; retune on M04/M66 and outcome [CE§1, CE§6 #2].
2. **Done-gate start mode**: (a) visible warn, (b) block now, (c) block 02/13/14, warn the rest. Rec (a); block per rule at ≥ 20 fires,
   FP ≤ 10%, after DONE-01 precision ≥ 0.9 [DG§5].
3. **reply_lint**: (a) warnings visible, (b) Stop hook OFF, keep `human-reply`, (c) as is. Rec (b); COM-01/15 BLOCK-once only at
   sampled precision ≥ 0.90; (c) is invalid, "keep warn" is no verdict [AC§4].
4. **Engram default**: (a) ON with the read rule + kill switch, (b) OFF, opt-in, (c) writes only, as today. Rec (a); flips OFF after 20
   sessions if recall-used < 0.2 and resume cost is not lower; sync/cloud off [EN§5, EN§7].
5. **Skill description cap**: (a) 60 tok (−311), (b) 50 (−451), (c) none. Rec (a) [TA§6 #4].
6. **Manual-only skills**: (a) `init-kit`, `post-review-comment`, `benchmark-release`, `real-environment-minutes`, `verify-per-commit`,
   `clean-pass`; (b) none. Rec (a): their descriptions leave the context [AC§2 p3, AC§3].
7. **Cold-start core**: (a) CONTEXT-PACK head + §4 (236 tok, cap 400), (b) whole pack (1,738), (c) none, fix `agent-protocol.md` §5. Rec (a) [TA§6 #6].
8. **Codex/Antigravity/OpenCode guards** (activation knows claude-code and pi only [AC§3, TA§5]): (a) declare unguarded, done gate via
   `done-check.sh` + skill step, native compaction knobs [CE§3 T3]; (b) refuse install; (c) port hooks now. Rec (a), then (c) per harness.
9. **Subagent report cap**: (a) 2,000 tok, (b) 4,000. Rec (a) [CE§4 A3]. 10. **`omitClaudeMd`**: (a) yes + rule-presence test, (b) no. Rec (a) [CE§4 A4].
11. **Activation thresholds**: (a) Google's 0.90/0.10, 20 fires, 7 days now, (b) calibrate first. Rec (a), recheck after one window [AC§4, AC§6].
12. **Default context budget per tier**: caps 15k-60k [TA§2] vs measured cartographers 96-110k, adversaries 106-146k [RM§4]. (a) role caps,
    (b) small 30k / medium 60k / large 120k [Assumed; Fable bound RM§3], (c) none until measured. Rec (b) provisional, moved by §4 rule.
