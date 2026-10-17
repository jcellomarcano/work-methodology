# Phase 1 findings: what the retrospective evidence supports, what it does not

Companion to `phase1-baseline.md` (the generated tables). Every number below comes from a row of that report or from `data/*.json` at the snapshot of 2026-10-13 (`sessions.json` tool sha `6f10acc8c0a0`, 110 sessions; live transcripts and the Engram database have moved on since). The label in brackets is the kit's own vocabulary (`METRICS.md`). Every before/after split depends on the adoption boundary, which is Inferred (earliest strong kit marker), so a "[Measured]" delta means measured counts on an inferred split. Nothing here is a causal claim: Phase 1 is correlational and its confounders are listed first, on purpose.

Correction history: (1) an independent verifier (2026-10-13) found §0.4 quoting an explorer's early estimate (40 of 81 / 0 of 13) instead of the report's rows; fixed. (2) The PR 176 pilot showed the `hook:metodo` marker matched the hook *command* string, so hooks that exited silently counted as kit runs; the marker now requires `[metodo]` in the hook output and every number below was regenerated from the corrected snapshot. The rule "no number without a report row" is enforced by rerunning `phase1_report.py` and by the verifier's recount.

## 0. Confounders that apply to every delta

1. **Model and effort drift.** Before the kit, project-a requests ran on `claude-fable-5`, `claude-opus-5`, `claude-opus-4-8` at `high`/`xhigh`. After it, on `claude-fable-5-1`, `claude-opus-5`, `claude-opus-5-5`, and 3,304 of 5,917 requests with a recorded effort ran at `medium` (the kit routes its subagents at medium). Lower effort alone shortens replies and latency. [Measured]
2. **Task mix.** Sessions are not comparable units of work; a session is whatever the user did that day. [Assumed]
3. **The user learned.** Prompting changed with the kit: median human prompt went from 166 to 112 characters in project-a, and prompts per session from 7 to 5. [Measured]
4. **Partial adoption.** Sessions with at least one real kit hook run (`[metodo]` output): project-a 42 of 85, project-d 0 of 5, project-b 0 of 7, project-c 0 of 1 (`data/sessions.json`, `hooks.metodo_runs`). Outside project-a the hooks never ran; those projects used kit subagents in a few sessions but their "after" is not the full kit. [Measured]
5. **Sessions span weeks.** Claude Code resumes sessions; 4 project-a sessions cross the adoption boundary and are excluded. [Measured]

Because of 1 and 2, every "before vs after" number is a hypothesis to test in Phase 2 with the same model, same effort and same tasks.

## 1. Headline numbers (project-a, the only project with the full kit)

Medians per session, before (n=31) vs after with kit (n=45). [Measured]

| Metric | Before | After, kit | Direction |
|---|---|---|---|
| Input tokens served (incl. cache) | 26.4M | 13.6M | lower |
| Output tokens | 129k | 63k | lower |
| Peak context in one request | 353k | 257k | lower |
| Cache hit ratio | 0.963 | 0.971 | flat |
| Subagent share of tokens | 0.16 | 0.29 | higher |
| Final reply length (chars) | 2,519 | 1,621 | shorter |
| Human prompt length (chars) | 166 | 103 | shorter |
| Time to first assistant record (s) | 19.3 | 7.0 | faster |
| Tool calls per human turn | 18.5 | 11.7 | lower |
| Engram recall calls | 0 | 0 | none |
| Engram save calls | 0 | 1 | marginal |
| Cost per session (USD, where recorded) | not recorded | 18.3 (n=38) | unknown before |

Reading: with the kit, project-a sessions are shorter in tokens, keep less in the parent context, and push more work to subagents. Whether that is the kit or the move to `medium` effort and newer models is exactly what Phase 2 isolates. The PR 176 pilot (`pilot-pr176.md`) adds a caution: when the kit is installed but not invoked, a session behaves exactly like vanilla, so "kit session" must mean "the kit ran", which is how the strong markers define it.

## 2. Context under multi-agent work (S22)

Four cells across all 106 sessions, kit (strong markers) × subagents. [Measured]

| Cell | n | Parent peak context | Subagent token share | Output tokens | Chars per Agent prompt |
|---|---|---|---|---|---|
| kit, with subagents | 39 | 373k | 0.45 | 105k | 2,873 |
| no kit, with subagents | 38 | 537k | 0.23 | 257k | 3,489 |
| kit, no subagents | 12 | 128k | — | 9k | — |
| no kit, no subagents | 21 | 129k | — | 24k | — |

Compactions are rare either way (median 0 per session; 0.004–0.005 per 1M input tokens in both multi-agent cells) because the models in use have 1M-token windows; each compaction drops ~940k tokens. [Measured] The kit's multi-agent sessions hold a smaller parent context (373k vs 537k) and hand shorter briefs to subagents (2,873 vs 3,489 chars); without subagents the two groups are the same size (128k vs 129k), so the context difference lives in how delegation is done, not in the kit's presence. The same confounders apply.

**H1 (Phase 2).** With the same model, effort and task, the kit's delegation rules lower parent peak context (M04, M09) and total output tokens (M02) without raising total tokens per completed task (M06).

## 3. Judges, adversaries, receipts (S7)

From the project-a tools instance, 2026-09-15 → 2026-10-13. [Measured]

- 50 RDD receipts, 10 voided. Verdicts: approved 4, rejected 13, inconclusive 14, escalated 10, none 9. 285 captures (judge, adversary, verifier runs).
- Subagent runs after adoption (project-a): judge 43, confrontador 45, adversario-puntos-ciegos 44, verificador 23, proposer 39, cartographer 20, comment-gate 15, mechanic 18.
- Budget hook: 135 `budget-deny` and 75 `budget-warn`. The agents that hit the cap most: mechanic 45, verificador 21, proposer 16+4, confrontador 11, cartographer 10.

What this does **not** tell: whether the 13 rejections were true defects, whether the 14 inconclusive rounds were worth their cost, or what was lost when a subagent was denied at its budget. There is no ground truth in the retrospective data. [Unknown]

**H2 (Phase 2).** Blind dual judges plus an adversary find more seeded defects than a single vanilla review (M25) with an acceptable false-finding rate (M26), at a measured token cost (M33).
**H3 (Phase 2).** Budget denials cut subagent output quality; measure findings per denied vs completed run.

## 4. Lints and communication (S8, S11)

- `reply_lint` fired 439 times, always `warn`, never block: COM-02 282, COM-15 145, COM-03 126, COM-05 98, COM-09 14. [Measured] The kit observes the rules more often than replies obey them, and nothing in the retrospective data says whether a warned reply was then fixed. [Unknown]
- Gates: `gate-push` warn 53 / allow 4 / deny 1, `gate-merge` warn 25 / deny 18, `force-push` deny 1, `forbidden-path` deny 10 / ask 7, `scope-outside` warn 50. The gates did stop 18 merges, 10 forbidden paths and 1 force push. [Measured]
- Delivery shape in project-a (git): Conventional Commit rate 0.35 → 0.88; code commits that ship tests 0.38 → 0.73. [Measured] Merge lead time: median 3.1 days (31 merges) before, 74 days after (3 merges). The after sample is three long-lived branches; it is not evidence that the kit slows delivery, and it is not evidence that it does not. [Unknown, n=3]
- project-b: conventional rate 0.98 → 0.53, tests-with-code 0.50 → 0.80, zero merges after the boundary. The project changed shape (no more merges), not necessarily practice. [Measured, Inferred]

**H4 (Phase 2).** Lints that only warn do not change reply conformance (M43); gates that block do change behaviour (M72). Test by comparing conformance of final replies across arms.

## 5. Memory: Engram (S3)

- 405 Engram sessions, 373 with zero observations (92%). project-a: 386 sessions, 363 with zero. [Measured counts; the per-project attribution is Engram's own]
- Transcripts: recall calls (`mem_search`, `mem_context`, …) median 0 in every group; 21 project-a sessions recalled at least once, 26 saved, 7 saved without ever recalling. 743 Engram tool calls across 35 sessions, most of them saves driven by the hook reminders. [Measured]
- Engram records no reads, so "memory was used" can only be shown from transcripts, and the transcripts show it was rarely used. [Measured]
- This benchmark itself used Engram for its feature-document mirror and conflict judging (relations: related 204, not_conflict 163, supersedes 18 [Measured]). That is bookkeeping by the agent, not evidence of value to the user. [Inferred]

Is the repo workable without Engram? On this evidence, yes: the feature document in `odd/tasks/` carries the same content as its mirror, and no session depended on a recall. What Engram adds today is a second copy and cross-session search that was almost never exercised. [Inferred]

**H5 (Phase 2, ablation arm `kit-no-engram`).** Removing Engram does not change task outcome or tokens on single-session tasks; on multi-session resumes it changes resume cost (M53). If H5 holds on resumes too, Engram is optional for this kit.

## 6. Router (S14)

`03-tools/config/model-tiers.json` is read by no code. Routing is the static `model:` frontmatter of each agent (haiku for mechanic/comment-gate/style/human-reviewer; sonnet for cartographer/proposer/judge/verificador/boundary; opus for confrontador/adversario) and no effort is set. Observed: after adoption, project-a ran 2,082 requests on `claude-opus-5-5`, 1,972 on `claude-opus-5`, 1,863 on `claude-fable-5-1`, and the kit's subagents at `medium` [Measured]. There is no routing log, so cost per tier and quality per tier cannot be attributed [Unknown].

**H6 (Phase 2).** Static role→model routing matches the quality of all-opus runs at lower cost (M62, M33). Needs per-request effort and model logged, which the kit does not do today.

## 7. Tokens: general-purpose vs specialized agents (S12, S13)

After adoption in project-a, specialized `generic-*` subagents account for 258 runs against 65 general-purpose/Explore/Plan runs; the subagent token share rose from 0.16 to 0.29 while the median session's input tokens fell from 26.4M to 13.6M. [Measured] Specialization moved tokens out of the parent context; whether it cut tokens per delivered change is unknown without a task unit (M06). [Unknown]

## 8. Skills, ways of working, MCP (S15, S16, S18)

- **Skills.** The kit installs 14 skills; after adoption the transcripts show 12 distinct kit skills invoked, 3 or fewer times each (`receipt-review` 3, `pr-message` 3, `review-comment` 3, `adversarial-round` 2). Adding a skill costs one `SKILL.md`, a registry line and an installer entry (`03-tools/bin/install-claude.sh`). [Measured]
- **MCP.** The kit wires one server, `metodo` (`03-tools/mcp/server.py`, configured by `03-tools/lib/mcp_config.py` into `.mcp.json`, env `METODO_TOOLS`/`METODO_REPO`): 306 calls in 15 sessions. Alongside it the sessions used engram (743 calls, 35 sessions), Claude_Browser (447), Atlassian/Jira (336), ccd session tools (66). The kit composes with other MCP servers by construction; nothing in it depends on them. [Measured]
- **Transferable without this tooling** [Assumed, reviewer judgment]: epistemic labels on every claim; evidence-or-silence; the change card; cartographer before surgery; two adversaries with a blind judge; work-unit commits with tests and docs; the PR and failure-report templates. **Tied to the tooling**: hooks and gates, RDD receipts, the `metodo` MCP server, budget caps, Engram mirrors, the model router.

## 9. Influences (S5)

| Kit mechanism | Stated influence | Where the kit says so |
|---|---|---|
| Clean Code / Robert C. Martin | one answer to "will it survive?" | `00-principles/why-layer.md:17` |
| Deterministic scripts, negative controls, determinism tests | "everything that can be a script is a script" | `00-principles/methodology.md:191-208`, `CONTEXT-PACK.md:43-45`, `03-tools/README.md:60` |
| ISO 24495-1:2023 (plain language) applied to code comments | six ISO 24495-code rules, `iso-24495-code` v0.6.2 | `01-roles/agents/generic-comment-gate.md:31`, `07-communication/sources/clear-language.md:19-63` |
| Plain-language sentence bounds (NN/g, GOV.UK/ONS) | 15–20 words per sentence | `07-communication/sources/clear-language.md:55-63` |
| Idempotency and transaction identity | one key per attempt | `00-principles/why-layer.md:37`, `07-communication/templates.md:25-32` |
| ODD / RDD (organic and receipt-driven development) | the orchestrator's workflow and the review receipt | gentle-ai 4.1.1 (external); surfaced in `~/.claude/CLAUDE.md`, not in this repo |
| Persistent memory | Engram 3.4.0 (external) | `03-tools/lib/engram_bridge.py` |
| Software Wasteland (Dave McComb) | named by the owner | **not cited anywhere in the kit** (rg: 0 hits) [Unknown] |

Citations are repository paths at the benchmark's commit; `cite_check.py` can verify them.

## 10. Bullshit meter: claim → evidence → status

"Status" is a verdict on the claim, not an epistemic label; the evidence column cites numbers whose labels are given in §1–§8 above.

| Claim the kit makes or implies | Evidence in Phase 1 | Status |
|---|---|---|
| Context is managed better (smaller parent context) | 353k → 257k peak; 373k vs 537k in multi-agent cells | supported, confounded (effort, models) |
| Replies are shorter and faster | 2,519 → 1,621 chars; 19.3 s → 7.0 s | supported, confounded (effort) |
| Work is delegated to specialized agents | subagent share 0.16 → 0.29; 266 generic-* runs | supported |
| Judges and adversaries catch defects | 13 rejected / 4 approved receipts | unknown: no ground truth |
| Lints keep replies within the rules | 439 warnings, 0 blocks, no fix evidence | unsupported so far |
| Gates prevent unsafe git actions | 18 merges, 10 paths, 1 force-push denied | supported |
| Commits ship with tests and follow conventions | 0.38 → 0.73, 0.35 → 0.88 (project-a) | supported, confounded (practice) |
| Delivery is faster | lead time 3.1 → 74 days, n=3 after | unknown |
| Engram gives continuity across sessions | recall median 0; 92% sessions save nothing | unsupported |
| The router picks the right model and effort | config unread, no log | unsupported (not implemented) |
| Everything is measured | hooks never ran outside project-a; no effort/model log; ledger lines undated | partly: the kit measures gates and lints, not its own routing or memory value |
| The kit's review beats what a team already has (PR 176 pilot, n=1) | kit 7 valid / 0 invalid at USD 8.4; Claude's `code-review` 8 valid / 0 invalid at USD 2.3; vanilla 6 / 0 at USD 1.3 | unsupported so far: more than vanilla, less than `code-review`, at 4–6× the cost |

## 11. What Phase 2 must do

Same model, same effort, same tasks, three arms (`vanilla`, `kit`, `kit-no-engram`), N tasks with seeded defects, repetitions, order and labels randomized, deterministic judges first and two blind LLM judges from different families for the qualitative axes. H1–H6 above are the pre-registered hypotheses; a hypothesis that Phase 2 does not confirm is reported as not confirmed. The PR 176 pilot (`protocols/pr-review-ab.md`) is the first cell and exists to debug the protocol, not to prove anything.
