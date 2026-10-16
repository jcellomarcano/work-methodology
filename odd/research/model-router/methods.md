# Research R5: routing and multi-agent methods (read 2026-10-16)

Lane: how to route by model and effort, and when to launch which subagents, for the best result at a sane cost.
Vendor-specific guidance (Anthropic, OpenAI, Google multi-agent advice, effort semantics, harness flags) lives in the
sibling dossiers `anthropic.md` §2-§4, `openai.md` §2-§4, `google.md` §2-§4, `local.md` §3; this file cites them instead
of repeating them. Tags: **[Reported]** = a number or claim as the source states it, not reproduced here; **[Measured]**
= kit measurement from `08-benchmark`; **[Inferred]** = our design reasoning; **[Unknown]** = open. Source ids `[Mn]`
and `[Kn]` are in §6.

## 1. Routing approaches compared

| Approach | What it optimizes | Evidence [Reported] | Failure modes |
|---|---|---|---|
| Static role→model (the kit today) | predictability, zero routing cost | none for the kit: no routing log, so cost and quality per tier "cannot be attributed" [K1 §6] | ignores task difficulty; no effort set; drifts as models change |
| Rule/feature-based (fixed table on facts) | auditability, determinism | Anthropic's routing workflow fits when "classification can be handled accurately, either by an LLM or a more traditional classification model/algorithm" [M19] | rules miss what the features do not encode; needs fixtures to stay honest |
| Learned classifier router (RouteLLM, Hybrid LLM) | cost at a target quality, per query | RouteLLM: "over 2 times in certain cases-without compromising the quality of responses" [M1]; Hybrid LLM: "up to 40% fewer calls to the large model, with no drop in response quality" [M4] | out-of-distribution collapse (below); needs preference or gold data; not deterministic across retrains |
| Cascade with verification (FrugalGPT, AutoMix) | cost, by trying cheap first and escalating | FrugalGPT: "up to 98% cost reduction or improve the accuracy over GPT-4 by 4% with the same cost" [M2]; AutoMix: "reducing computational cost by over 50% for comparable performance" [M3] | the escalation signal is noisy; latency adds up; the cheap call is wasted on hard inputs |
| Effort-only scaling (same model, more thinking) | quality per model without a second model | Snell et al.: compute-optimal allocation is "more than 4x" more efficient than best-of-N [M6]; Anthropic levels in `anthropic.md` §2 | gains vanish on the hardest prompts (§3); `max` "can lead to overthinking" [M20] |
| Self-consistency / voting | accuracy on tasks with a single checkable answer | "GSM8K (+17.9%)" [M9]; "scales with the number of agents instantiated" [M14] | non-monotone in the number of calls [M15]; plateaus without a verifier [M7] |
| Debate / adversarial pairs | divergent thinking, catching confident errors | Du et al.: instances "propose and debate their individual responses and reasoning processes over multiple rounds" [M10] | "do not reliably outperform" self-consistency [M12]; judge bias across model families [M11] |
| Market/aggregate routers (OpenRouter Auto) | convenience | "A fast, lightweight classifier assigns each prompt one of ~30 fine-grained task types" and ranks by spend [M23] | popularity is not quality on our briefs; opaque; not reproducible offline |

- **Learned routers do not transfer to unseen task types.** RouteLLM on MMLU: "all routers perform poorly at the level
  of the random router when trained only on Arena dataset, which we attribute to most MMLU questions being
  out-of-distribution" [M1]. Model swaps transfer better: "our best routers requiring approximately half the GPT-4 calls
  of the random router to achieve CPT(80%) when routing between both the Claude 3 and Llama 3.1 family of models" [M1].
  No labelled kit data exists yet, so a learned router waits for Phase 2 data [Inferred].
- **Cascades need a verifier, and self-verification is noisy.** AutoMix "routes queries to larger LMs, based on the
  approximate correctness of outputs from a smaller LM" and, "given that self-verification can be noisy, it employs a
  POMDP based router" [M3]. Intrinsic self-correction is weak: "LLMs struggle to self-correct their responses without
  external feedback, and at times, their performance even degrades after self-correction" [M13]. The kit already has
  external verifiers (`round_output.py`, `cite_check.py`, tests), which is what makes a cascade safe here [Inferred].
- **Difficulty is the shared variable.** Hybrid LLM routes "based on the predicted query difficulty and the desired
  quality level" [M4]; RouterBench: "no single model can optimally address all tasks and applications, particularly when
  balancing performance with cost", benchmarked on "over 405k inference outcomes" [M5].
- **Voting has an optimum, not a slope.** "the performance of both Vote and Filter-Vote can first increase but then
  decrease as a function of the number of LM calls"; "more LM calls lead to higher performance on "easy" queries, but
  lower performance on "hard" queries" [M15]. Repeated sampling pays where answers are auto-checkable: SWE-bench Lite
  solve rate "increases from 15.9% with one sample to 56% with 250 samples", but "In domains without automatic
  verifiers, we find that common methods for picking from a sample collection (majority voting and reward models)
  plateau beyond several hundred samples" [M7].
- **Debate is fragile.** Self-reflection suffers Degeneration-of-Thought: "once the LLM has established confidence in
  its solutions, it is unable to generate novel thoughts later through reflection even if its initial stance is
  incorrect"; and "LLMs might not be a fair judge if different LLMs are used for agents" [M11]. Debate protocols are
  "more sensitive to different hyperparameter settings and difficult to optimize" [M12]. The kit's adversaries never
  talk (a judge rules on file:line evidence): no tuning problem, but the judge-bias risk stays [Inferred].

## 2. When multi-agent pays off and when it hurts

Pays off (breadth, isolation):
- Anthropic's research system: token spend is the main driver ("three factors explained 95% of the performance variance
  in the BrowseComp evaluation") and the model is a multiplier: "upgrading to Claude Sonnet 4 is a larger performance
  gain than doubling the token budget on Claude Sonnet 3.7" [M18]. The 90.2% gain, the "15×" token multiplier and the
  3-5 parallel subagents are quoted in `anthropic.md` §4. Economics: "For economic viability, multi-agent systems
  require tasks where the value of the task is high enough to pay for the increased performance" [M18].
- Kit [Measured, K1 §2]: sessions with kit subagents held a parent peak context of 373k vs 537k without the kit (both
  with subagents), and 2,873 vs 3,489 chars per brief; without subagents the two groups are equal (128k vs 129k).
  Isolation helps the parent; it says nothing yet about quality per task.

Hurts (coordination, shared state, verification):
- Cognition: "Share context, and share full agent traces, not just individual messages" and "Actions carry implicit
  decisions, and conflicting decisions carry bad results"; "running multiple agents in collaboration only results in
  fragile systems. The decision-making ends up being too dispersed and context isn’t able to be shared thoroughly enough
  between the agents." Default: "The simplest way to follow the principles is to just use a single-threaded linear
  agent" [M21]. On Claude Code subagents (as of June 2025): "it never does work in parallel with the subtask agent, and
  the subtask agent is usually only tasked with answering a question, not writing any code" [M21].
- MAST (1600+ traces, 7 frameworks): gains "are often minimal" [M16]; "14 unique modes, clustered into 3 categories"
  [M16]. Largest modes: "step repetitions (FM-1.3, 15.7%)", "mismatches between reasoning and action (FM-2.6, 13.2%)",
  "no or incomplete verification (FM-3.2, 8.20%), or incorrect verification (FM-3.3, 9.10%)"; "many existing verifiers
  perform only superficial checks" [M16]. Fixes that worked: "improving agent role specifications alone yields a +9.4%
  success rate increase for ChatDev" and "adding a high-level task objective verification step to ChatDev yields a
  +15.6% improvement in task success on ProgramDev" [M16].
- Anthropic's own failures: "Early agents made errors like spawning 50 subagents for simple queries"; "Without detailed
  task descriptions, agents duplicate work, leave gaps, or fail to find necessary information."; and "Agents struggle to
  judge appropriate effort for different tasks, so we embedded scaling rules in the prompts" [M18]. Hence a
  deterministic router.
- Start single: Google "If you're early in your agent development, we recommend that you start with a single agent."
  [M22]; Anthropic "we recommend finding the simplest solution possible, and only increasing complexity when needed"
  [M19]; OpenAI's equivalent is in `openai.md` §4.
- Kit [Measured, K2 §4-§5, n=1 PR]: the full kit review (judge + challenger + blind-spot adversary, all opus-high) found
  7 valid findings for USD 8.38 and 57 turns; vanilla found 6 for USD 1.34; Claude's `code-review` skill (one
  general-purpose subagent) found 8 for USD 2.25. The opus roster cost 6.3× vanilla for +1 valid finding.

Synthesis [Inferred]: launch parallel subagents for **read-only breadth** (mapping independent modules, independent
review lenses) and for **verification by a different context**; keep **writes and dependent chains in one agent**; never
let agents negotiate with each other; spend the extra roles only where the risk tier pays for them.

## 3. Effort vs model size

- Test-time compute can replace a bigger model on easy-to-medium prompts: "test-time compute can be used to outperform a
  14x larger model" "on problems where a smaller base model attains somewhat non-trivial success rates" [M6].
  FLOPs-matched, test-time compute wins if "we expect mostly easy or intermediate difficulty questions" [M6].
- It does not rescue the hardest prompts: "On the most difficult questions (level 5), no method makes much meaningful
  progress." [M6]. Effectiveness "critically varies depending on the difficulty of the prompt" [M6].
- Smaller model plus better inference can be Pareto-optimal: Llemma-7B with tree search "consistently outperforms the
  Llemma-34B model across all tested inference strategies on the MATH benchmark" [M8].
- Revisions can undo right answers: "around 38% of correct answers get converted back to incorrect ones with our
  revision model using a naïve approach" [M6]. Keep a verifier between rounds.
- Vendor rule of thumb (quoted in `anthropic.md` §2): wrong with full context → more capable model; wrong by skipping a
  file or not running tests → higher effort. `max` on Opus 4.7: "On most workloads `max` adds significant cost for
  relatively small quality gains, and on some structured-output or less intelligence-sensitive tasks it can lead to
  overthinking" [M20].
- Kit confounder [Measured, K1 §0.1]: 3,304 of 5,917 post-adoption requests with a recorded effort ran at `medium`.

Decision rule [Inferred]: raise **effort** when the failure is diligence (truncated, `not_covered`, skipped tests,
schema miss) and the task is within the model's reach; raise **model tier** when the output is wrong with full context,
on novel or critical-path work, or after one effort bump failed; use **sampling/voting** only where an automatic
verifier exists (tests, `cite_check.py`, schema).

## 4. A deterministic routing design for this kit [Inferred]

Inputs, all computable without an LLM, each with its producer:

| Input | Source in the kit | Values |
|---|---|---|
| `tier` | `rdd_risk.derive()` | exempt, low, medium, high |
| `lane` | `change_card_validator` `routing` | opus, sonnet, none (no card) |
| `critical_hit`, `owner_gate` | `rdd_risk` reasons (shared_build, money_paths), `lens_focus`, `owner_gate` | bools + lens |
| `changed_lines`, `modules`, `languages` | `diff_facts()`; module = top-level build unit; file extensions | ints, set |
| `test_sectors` | `project.json` `test_sectors`, `full_required` | set, bool |
| `task_kind` | the skill or command invoked | review, implement, map, comment, docs |
| `map_age_days` | cartographer output timestamp | int or none |
| `budget_usd` | change card budget (new field) | float or none |
| `offline` | privacy/offline flag (new, project or env) | bool |
| `admitted` | `model-tiers.json` entries with `status: admitted` per tier/provider | set |
| `prior` | last round outputs: `truncated`, schema PASS, verdict, disagreement | facts |

Decision table: D0-D6 first match wins (like `rdd_risk`), D7-D8 are post-passes; effort is the per-role default; model
ids come from `model-tiers.json` (`admitted` only, `candidate` only in a trial slot), so the table never names a model.

| # | Condition | Roster (role: tier/effort, launch, mode) | Escalation |
|---|---|---|---|
| D0 | `review`, `tier=exempt` | none; scripts only (`docs_lint`) | none |
| D1 | `review`, `tier=low`; or `task_kind=comment` | scripts (contract, `comment_gate.py`); `comment-gate`: small/low only if new comments > 0 | small P0 → verify on medium |
| D2 | `task_kind=map` | cartographer: small/medium if `modules=1`, medium/medium if more; one per module, parallel, max 3 | truncated → split scope, relaunch once |
| D3 | `implement`, `tier≤medium` (tier from the card's planned paths) | cartographer only if `map_age_days>7`; proposer medium/medium, single, sequential; verifier medium/high after | verifier FAIL → proposer again once; second → owner |
| D4 | `implement`, `tier=high` | as D3 with proposer medium/high; then D6 review roster | as D6 |
| D5 | `review`, `tier=medium` | challenger medium/high with `lens_focus`; sector verifier medium/medium; both parallel (read-only); judge medium/high only if findings > 0 | P0 or critical property → judge large/high |
| D6 | `review`, `tier=high` | challenger large/high + blind-spot adversary large/high, parallel; verifier medium/high; judge medium/high; owner consent first | P0/critical → judge large/xhigh; adversary disagreement → judge large |
| D7 | `offline=true` | same roles, models restricted to admitted local entries | no admitted local model for a mandatory role → `blocked`, never a silent remote call |
| D8 | `budget_usd` set | estimated cost > `budget_usd` → drop optional roles in fixed order: trial third adversary, judge-on-zero-findings, stale-map cartographer | mandatory roles of `tier` are never dropped → `over_budget`, owner decides |

Objective (best result): lexicographic, not a weighted sum. (1) Every mandatory role of the RDD tier is present
(`review-receipt.md` §3); (2) quality signals: verify-above for any small-model critical finding and escalation on
disagreement, truncation or schema failure (`model-routing.md`, `agent-protocol.md` §2); (3) cheapest roster that
satisfies (1) and (2) under `budget_usd`. Quality is never traded for cost at the high tier; budget only prunes optional
roles.

Offline evaluation, deterministic:
- **Fixtures**: `tests/fixtures/router/*.json`, each an input set plus the expected roster, covering every row D0-D8 and
  boundary cases (`changed_lines` = `low_max_changed_lines` and +1; card missing; shared build touched; offline with and
  without an admitted local model).
- **Cost model**: per role, `tokens_in × usd_in + tokens_out × usd_out` from `model-tiers.json`, token estimates seeded
  from kit measurements (cartographers 96k-110k; large adversaries 106k-146k; scoped small cartography 26k-30k,
  `model-routing.md` and `multi-provider-routing.md` §2) and capped at `max_context_tokens`.
- **Metrics**: roster exact match; under-provisioning (a mandatory role missing: must be 0); over-provisioning
  (estimated cost ÷ cost of the minimal correct roster); effort correctness per role.
- **Negative controls**: same input twice → byte-identical output; shuffled `touched_paths` → same output; a `candidate`
  or `rejected` model is never selected outside a trial slot; `offline` never yields a remote provider; an unknown
  `task_kind` fails closed.
- **Calibration later**: Phase 2 H6 (static vs all-opus, K1 §6) needs per-request model and effort logged; the router
  writes that line so cost and quality per tier become measurable [Unknown until then].

## 5. Launch rules for the kit

1. **No review subagent below `medium`** (D0, D1): exempt and low reviews close with scripts. Justification: simplest
   solution first [M19][M22]; K2 shows extra roles cost 6.3× for +1 finding on one PR [Measured].
2. **Read in parallel, write alone.** Parallel only for read-only roles (cartographers per module, challenger +
   verifier, the two adversaries); the proposer and mechanic run single and sequential. Justification: implicit
   conflicting decisions [M21]; MAST coordination failures [M16].
3. **Max fan-out 3 parallel subagents per step, depth 1** (`may_spawn: []`). Justification: Anthropic's 3-5 for
   research, with "most coding tasks involve fewer truly parallelizable tasks than research" (`anthropic.md` §4); the
   "50 subagents for simple queries" failure [M18].
4. **Effort defaults**: small `low` (closed-schema verdict), mechanic `medium`; medium-tier `medium` for cartographer
   and proposer, `high` for verifier and judge; large `high`; `xhigh` only on critical path at the high tier; never
   `max` by default. Justification: `anthropic.md` §5 mapping; `max` overthinking [M20]; set once per agent because
   changing effort invalidates the cache (`anthropic.md` §2).
5. **Escalate one step at a time**: diligence failure → effort +1 once; still wrong or wrong with full context → tier +1
   [§3]. Truncated output is never clean; relaunch with less scope once (`agent-protocol.md` §2).
6. **Verify above**: a P0 from a small or medium role is confirmed by the next tier before it counts
   (`model-routing.md`); a verifier must run real checks, not compile-only [M16].
7. **Stop rules**: two stalls → owner (`model-routing.md`); second `rejected` → escalated (`review-receipt.md` §4); no
   voting without an automatic verifier [M7][M15].
8. **Heterogeneity as a trial slot, not a debate**: a third adversary from another provider runs as `trial` only when
   admitted elsewhere and budget allows; the judge rules blind to the source, since cross-family judging is biased [M11]
   (`multi-provider-routing.md` §2).

## 6. Sources (all read 2026-10-16 with `curl -sL`; HTTP status of the final URL)

| Id | Source | URL | Status |
|---|---|---|---|
| M1 | Ong et al., "RouteLLM: Learning to Route LLMs with Preference Data" (2024), abstract + full HTML | https://arxiv.org/abs/2406.18665 , https://arxiv.org/html/2406.18665 | 200, 200 |
| M2 | Chen, Zaharia, Zou, "FrugalGPT" (2023) | https://arxiv.org/abs/2305.05176 | 200 |
| M3 | Aggarwal et al., "AutoMix: Automatically Mixing Language Models" (2023) | https://arxiv.org/abs/2310.12963 | 200 |
| M4 | Ding et al., "Hybrid LLM: Cost-Efficient and Quality-Aware Query Routing" (2024) | https://arxiv.org/abs/2404.14618 | 200 |
| M5 | Hu et al., "RouterBench: A Benchmark for Multi-LLM Routing System" (2024) | https://arxiv.org/abs/2403.12031 | 200 |
| M6 | Snell, Lee, Xu, Kumar, "Scaling LLM Test-Time Compute Optimally…" (2024), abstract + full HTML | https://arxiv.org/abs/2408.03314 , https://arxiv.org/html/2408.03314 | 200, 200 |
| M7 | Brown et al., "Large Language Monkeys" (2024) | https://arxiv.org/abs/2407.21787 | 200 |
| M8 | Wu et al., "Inference Scaling Laws" (2024) | https://arxiv.org/abs/2408.00724 | 200 |
| M9 | Wang et al., "Self-Consistency Improves Chain of Thought Reasoning" (2022) | https://arxiv.org/abs/2203.11171 | 200 |
| M10 | Du et al., "Improving Factuality and Reasoning … through Multiagent Debate" (2023) | https://arxiv.org/abs/2305.14325 | 200 |
| M11 | Liang et al., "Encouraging Divergent Thinking … through Multi-Agent Debate" (2023) | https://arxiv.org/abs/2305.19118 | 200 |
| M12 | Smit et al., "Should we be going MAD?" (2023) | https://arxiv.org/abs/2311.17371 | 200 |
| M13 | Huang et al., "Large Language Models Cannot Self-Correct Reasoning Yet" (2023) | https://arxiv.org/abs/2310.01798 | 200 |
| M14 | Li et al., "More Agents Is All You Need" (2024) | https://arxiv.org/abs/2402.05120 | 200 |
| M15 | Chen et al., "Are More LLM Calls All You Need?" (2024) | https://arxiv.org/abs/2403.02419 | 200 |
| M16 | Cemri et al., "Why Do Multi-Agent LLM Systems Fail?" (2025), abstract + full HTML | https://arxiv.org/abs/2503.13657 , https://arxiv.org/html/2503.13657 | 200, 200 |
| M18 | Anthropic, "How we built our multi-agent research system" | https://www.anthropic.com/engineering/multi-agent-research-system | 200 |
| M19 | Anthropic, "Building Effective AI Agents" | https://www.anthropic.com/engineering/building-effective-agents | 200 |
| M20 | Anthropic, effort docs | https://platform.claude.com/docs/en/build-with-claude/effort.md | 200 |
| M21 | Walden Yan (Cognition), "Don't Build Multi-Agents", 2025-06-12 | https://cognition.ai/blog/dont-build-multi-agents | 200 |
| M22 | Google Cloud, "Choose a design pattern for your agentic AI system" | https://cloud.google.com/architecture/choose-design-pattern-agentic-ai-system | 200 |
| M23 | OpenRouter, Auto Router docs | https://openrouter.ai/docs/features/model-routing | 200 |
| K1 | `08-benchmark/reports/phase1-findings.md` §0-§3, §6 (kit, snapshot 2026-10-13) | local file | n/a |
| K2 | `08-benchmark/reports/pilot-pr176.md` (kit, 2026-10-13) | local file | n/a |

Fetched but not cited: `openrouter.ai/openrouter/auto`, `docs.litellm.ai/docs/routing` and `/proxy/auto_routing`
(availability-based fallbacks, not difficulty routing), OpenAI's agents guide PDF (covered by `openai.md`), all 200.
Failure: `google.github.io/adk-docs/agents/multi-agents/` gave 200 but only a client-side redirect stub; not cited.
