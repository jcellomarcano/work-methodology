# Research R1: Anthropic Claude, models and effort for routing

Lane R1 of `odd/tasks/model-router.md` (S2, S3). Read date for every source: **2026-10-16**. Tags: [Measured] observed locally, [Stated] fetched and quoted from Anthropic, [Inferred] our reading, [Unknown] not stated anywhere fetched. Source IDs `[Sn]` are listed in §6. Prices are USD per million tokens (MTok), and they expire.

## 1. Model table (current lineup, Claude API) [Stated]

| Field | Claude Fable 5.1 | Claude Opus 5.5 | Claude Sonnet 5.5 | Claude Haiku 5.5 |
|---|---|---|---|---|
| API id = API alias [S1] | `claude-fable-5-1` | `claude-opus-5-5` | `claude-sonnet-5-5` | `claude-haiku-5-5` |
| Claude Code alias [S8] | `fable` (also `best`) | `opus` | `sonnet` | `haiku` |
| Released [S3-S6] | 2026-09-01 | 2026-09-22 | 2026-09-28 | 2026-10-07 |
| Context / max output [S1] | 1M / 128K | 1M / 128K | 1M / 128K | 1M / 128K |
| Batch max output (beta header `output-300k-2026-03-24`) [S1] | Unknown (not in the list) | 300K | 300K | 300K |
| Input / output [S2] | $10 / $50 | $4 / $20 | $2 / $10 | $0.10 / $0.50 for prompts ≤100K tokens; $0.50 / $2.50 for prompts >100K |
| 5m write / 1h write / cache read [S2] | $12.50 / $20 / $0.25 | $5 / $8 / $0.20 | $2.50 / $4 / $0.10 | $0.125 / $0.20 / $0.01 (≤100K); $0.625 / $1 / $0.05 (>100K) |
| Batch API [S2] | $5 / $25 | $2 / $10 | $1 / $5 | $0.05 / $0.25 (≤100K); $0.25 / $1.25 (>100K) |
| Fast mode [S2] | n/a | $8 / $40 | n/a | n/a |
| Thinking [S1] | Adaptive (always on) | Adaptive (always on) | Adaptive | Adaptive |
| Effort levels [S9] | low, medium, high, xhigh, max | same five | same five | same five |
| Default effort, API [S1] | `high` | `medium` | `high` | `medium` |
| Default effort, Claude Code [S8] | `high` | `medium` | `medium` | `medium` |
| Can thinking be turned off? [S8][S9] | No | No (400 error) | No; lowest is `thinking: between_tools` at low/medium/high | Via API only at `high` or below; not in Claude Code |
| Per-message effort (beta `mid-conversation-output-config-2026-07-01`) [S9] | Yes | Yes | Yes | Yes (Claude API, Google Cloud) |
| Latency, relative [S1] | Slower | Moderate | Fast | Fastest |
| Reliable knowledge / training cutoff [S1] | Jun 2026 / Jun 2026 | Jun 2026 / Jun 2026 | Jun 2026 / Jun 2026 | Jun 2026 / Jun 2026 |
| Status, retirement [S7] | Active, not sooner than 2027-09-01 | Active, not sooner than 2027-09-22 | Active, not sooner than 2027-09-28 | Active, not sooner than 2027-10-07 |
| Stated purpose [S1] | "For demanding reasoning and long-horizon agentic work" | "For long-running agentic coding and knowledge work" | "The best combination of speed and intelligence" | "For high-volume, latency-sensitive tasks such as classification, extraction, and routing" |

- **Claude Mythos 5.1** (`claude-mythos-5-1`) is the same model as Fable 5.1, but only for verified programs: "Claude Fable 5.1 and Claude Mythos 5.1 are the same model, but with different levels of safeguards." [S13]. It is not routable for the kit.
- **Legacy, still available** [S1][S7]: Fable 5, Opus 5, Opus 4.8, 4.7, 4.6, 4.5, Sonnet 5, Sonnet 4.6, Haiku 4.5. The kit's incumbents in `multi-provider-routing.md` (Haiku 4.5, Sonnet 5, Opus 5) are now legacy. `claude-haiku-4-5-20251001` shows "Not sooner than October 15, 2026" [S7], a date that has already passed.
- **Tokenizer** [S2]: "This tokenizer produces approximately 30% more tokens for the same text." This applies to Claude 4.7 and later. Compare models per task, not per token.
- **Long context** [S2]: everything from 4.6 onward bills 1M at the standard rate, except Haiku 5.5. On Haiku 5.5, "a request whose prompt is over 100,000 tokens pays higher prices."
- **Manual thinking budgets** [S10]: `budget_tokens` (minimum 1,024) applies only to older models. "Claude 4.7 and later models do not support it and reject requests that use it, returning a 400 error." On all four current models, effort is the only thinking control.

## 2. Effort semantics [Stated]

| Level | What it changes [S11] | Anthropic's typical use [S9] | Claude Code guidance [S8] |
|---|---|---|---|
| `low` | "Claude minimizes thinking. Skips thinking for simple tasks where speed matters most." | "Simpler tasks that need the best speed and lowest costs, such as subagents" | "Quick exchanges where you review each result" |
| `medium` | "Claude uses moderate thinking. May skip thinking for simple queries." | "Agentic tasks that require a balance of speed, cost, and performance" | Default on Opus/Sonnet/Haiku 5.5 |
| `high` | "Claude thinks on most requests that benefit from it. Provides deep reasoning on complex tasks." | "Complex reasoning, difficult coding problems, agentic tasks" | "Work where verification matters or edge cases are likely, such as fixing a bug in an existing codebase" |
| `xhigh` | "Claude thinks more readily and at greater depth than at `high`, suited to extended exploration." | "Long-running agentic and coding tasks (over 30 minutes) with token budgets in the millions" | "Deeper reasoning at higher token spend" |
| `max` | "Claude thinks the most readily and at the greatest depth, with no constraint on thinking length." | "Tasks requiring the deepest possible reasoning and most thorough analysis" | "may show diminishing returns and is prone to overthinking, so test before adopting it broadly" |

- Effort is not just thinking. Per [S9]: "The effort parameter affects **all tokens** in the response". Also: "Lower effort also means fewer and terser tool calls." And: "Effort is a behavioral signal, not a strict token budget."
- Effort is calibrated per model. [S8]: "the same level name does not represent the same underlying value across models." [S9] on Sonnet 5.5: "Its levels are recalibrated".
- **Per-model starting points** [S9]:
  - Fable 5.1: "Start with `high`, the default."
  - Sonnet 5.5: "For agentic coding and multistep tool use, start with `medium` for well-specified tasks and move to `high` for harder or longer ones."
  - Haiku 5.5: "Start with `medium`" and "Use `high` for knowledge work, longer agent tasks, and strict instruction following." It also warns: "In long agent prompts, the model is more likely to skip a search, stop early, or skip a check at `low`."
- **Measured by Anthropic, Opus 5.5 on a SWE-bench Pro subset, cost per task** [S12]: low 87.4% at $0.11; medium 92.8% at $0.21; high 95.3% at $0.29; xhigh 96.7% at $0.74. On research, "Claude Fable 5.1 scored nearly the same from `low` to `high` on DeepResearch Bench II".
- **Escalation policy** [S12]: "run every task at a low setting and re-run only the failures at a higher one." The measured result was "`low`, failures re-run at `high`": "About 97%" solved at "About $0.17 USD", against $0.29 for everything at `high`. The condition: "you need a failure signal".
- **Model vs effort** [S14]: "If Claude has all the pertinent context, clearly tried, and still got it wrong, that's a signal to pick a more capable model. If Claude got it wrong by skipping a file, not running the tests, or bailing on a refactor partway through, pick a higher effort level."
- **Cache** [S9]: "Changing the top-level effort value between requests invalidates prompt caching". Fix the effort level per agent session; do not change it per turn.

## 3. Harness controls: Claude Code [Measured + Stated]

[Measured] The local `claude --help` (Claude Code 2.1.301) prints:
- `--model`: "Model for the current session. Provide an alias for the latest model (e.g. 'fable', 'opus', or 'sonnet') or a model's full name."
- `--effort <level>`: "(low, medium, high, xhigh, max)"
- `--fallback-model`: "Accepts a comma-separated list to try each in order."

| Control | Exact syntax | Notes |
|---|---|---|
| Session model | `/model <alias\|name>` > `claude --model opus` > `ANTHROPIC_MODEL` > settings `"model": "opus"` > `ANTHROPIC_DEFAULT_MODEL` | Priority order per [S8] |
| Aliases [S8] | `default`, `best`, `fable`, `opus`, `sonnet`, `haiku`, `sonnet[1m]`, `opus[1m]`, `opusplan` | On the Anthropic API, `opus` → Opus 5.5, `sonnet` → Sonnet 5.5, `haiku` → Haiku 5.5. Aliases lag on Bedrock, Vertex and Foundry (e.g. Sonnet 4.5, Haiku 4.5) |
| Pin an alias | `ANTHROPIC_DEFAULT_{FABLE,OPUS,SONNET,HAIKU}_MODEL=<full id>` | "To pin to a specific version, use the full model name" [S8] |
| `default` [S8] | resolves to Opus 5.5 on Pro, Max, Team, Enterprise and the API | "Neither Fable model is the account-type default on any plan or provider." |
| `opusplan` [S8] | "uses `opus` during plan mode, then switches to `sonnet` for execution" | Built-in two-tier hybrid |
| Subagent model [S15] | frontmatter `model: sonnet\|opus\|haiku\|fable\|claude-opus-5-5\|inherit` | Resolution order: per-invocation `model` param > frontmatter > `CLAUDE_CODE_SUBAGENT_MODEL` > main model |
| Force one model on all subagents | `CLAUDE_CODE_SUBAGENT_MODEL=haiku` + `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` | With FORCE on, "Claude Code ignores the `model` field in subagent definitions" [S15] |
| Family-alias gotcha [S15] | `model: opus` while the main session is on Opus | The subagent "runs on the main conversation's exact model". Pin full ids if exact versions matter |
| Session effort | `CLAUDE_CODE_EFFORT_LEVEL` / `--effort` / `/effort` > settings `modelSettings` / `effortLevel` > model default | Settings do not accept `max`. A level above what the model supports falls back to the highest supported level at or below it [S8] |
| Subagent/skill effort [S15] | frontmatter `effort: low\|medium\|high\|xhigh\|max`; per-invocation `effort` param (v2.1.292+) | "The `CLAUDE_CODE_EFFORT_LEVEL` environment variable takes precedence over both." [S15] |
| Effort cap [S16] | `"maxEffortLevel": "medium"`, optionally per model under `modelSettings` | Caps frontmatter too; the lowest cap across scopes wins |
| Thinking for subagents [S15] | inherited from the session | "There is no per-subagent thinking setting." |
| Availability fallback [S8][S16] | `claude --fallback-model sonnet,haiku` or `"fallbackModel": ["claude-sonnet-5", "claude-haiku-4-5"]` | At most 3 models. Applies for the current turn only and also covers subagents. Never falls back to a smaller context window during compaction |
| Content fallback [S8] | automatic | Fable 5.1 and Opus 5.5 re-run cyber-flagged requests on Opus 4.8 and bio-flagged ones on Opus 5. Sonnet 5.5 re-runs cyber-flagged requests on Sonnet 5 |
| Nesting / concurrency [S15] | `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` (default 3), `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (default 20) | Set `1` to turn off nesting |
| One-off deep turn [S8] | `ultrathink` in the prompt | "The effort level sent to the API is unchanged." |

Built-in Explore: when the session runs Fable, Explore runs on `opus`. A project agent named `Explore` with `model: haiku` overrides it [S15].

## 4. Anthropic on multi-agent orchestration [Stated, verbatim]

- **Lead vs workers** [S17]: "a multi-agent system with Claude Opus 4 as the lead agent and Claude Sonnet 4 subagents outperformed single-agent Claude Opus 4 by 90.2% on our internal research eval."
- **Why it works** [S17]: "Multi-agent systems work mainly because they help spend enough tokens to solve the problem." Also: "token usage by itself explains 80% of the variance".
- **Cost multiplier** [S17]: "agents typically use about 4× more tokens than chat interactions, and multi-agent systems use about 15× more tokens than chats."
- **When not to** [S17]: "some domains that require all agents to share the same context or involve many dependencies between agents are not a good fit for multi-agent systems today." And: "most coding tasks involve fewer truly parallelizable tasks than research".
- **Scaling rules** [S17]: "Simple fact-finding requires just 1 agent with 3-10 tool calls, direct comparisons might need 2-4 subagents with 10-15 calls each, and complex research might use more than 10 subagents with clearly divided responsibilities."
- **Parallelism** [S17]: "the lead agent spins up 3-5 subagents in parallel rather than serially; (2) the subagents use 3+ tools in parallel." Reported effect: "These changes cut research time by up to 90% for complex queries".
- **Briefs** [S17]: "Each subagent needs an objective, an output format, guidance on the tools and sources to use, and clear task boundaries."
- **Handoff by artifact** [S17]: "Subagents call tools to store their work in external systems, then pass lightweight references back to the coordinator."
- **Current measurements** [S12]: "Delegation saved money in only two situations". When those do not apply: "When the work is one dependent chain, or fits in a single context without a long cost tail, the orchestrator's model alone at lower effort came out ahead in every case measured".
- **Order of levers** [S12]: "Tune one model before you add a second". Also: "Build a pairing only if it beats the single model's whole curve of score against spend."
- **Advisor pattern** [S12]: "An advisor can help only when the executor consults it." The orchestrator pattern "Fits" "Work that fans out across genuinely independent files, documents, or cases, especially more than one context window of it".
- **Claude Code** [S15]:
  - Use subagents when "The task produces verbose output you don't need in your main context" or "The work is self-contained and can return a summary".
  - Stay in the main conversation when "Multiple phases share significant context, such as planning, implementation, and testing".
- **Worker model** [S6]: Haiku 5.5 "pairs well with Opus 5.5 and Sonnet 5.5 as a subagent on coding work". By contrast, "Sonnet 5.5 and Opus 5.5 remain better choices for complex agentic coding tasks".
- **Upgrade before routing** [S12]: Opus 5 to Opus 5.5 gave "78% less per solved task". Cheap Opus as an alternative: "Opus 5.5 at `low` solved about the same share of tasks as Sonnet 5.5 at its default, inside run-to-run noise, for about 7% more per solved task."

## 5. Tier mapping proposal for the kit [Inferred]

Each line is our proposal, justified by the quoted text. Admission still follows `multi-provider-routing.md` §4. A proposal is not an admission.

| Kit tier | Model (CC alias / pinned id) | Effort | Justification (quote, source) |
|---|---|---|---|
| small (rulebook verdict, 15k) | `haiku` / `claude-haiku-5-5` | `low` for closed-schema verdicts; `medium` when the role edits (mechanic) | "classification, routing, extraction, and subagent tasks" [S6]; "Use `low`, the cheapest and fastest level, for chat, short tool tasks, and simple, high-volume requests." [S9] |
| medium (cartographer, verifier, proposer, judge without P0) | `sonnet` / `claude-sonnet-5-5` | `medium` for scoped reads and well-specified proposals; `high` for verifier and judge | "start with `medium` for well-specified tasks and move to `high` for harder or longer ones" [S9]; `high` is for "Work where verification matters or edge cases are likely" [S8] |
| large (challenger, blind-spot adversary, judge on P0) | `opus` / `claude-opus-5-5` | `high`; `xhigh` on the critical path | "92.8% of tasks solved" at `medium` vs "95.3% of tasks solved" at `high` [S12]; `xhigh` is for "Long-running agentic and coding tasks (over 30 minutes) with token budgets in the millions" [S9] |
| orchestrator (designs, decides, talks to the owner) | `opus` / `claude-opus-5-5` by default; `fable` / `claude-fable-5-1` on escalation | `high` | "start with Claude Opus 5.5 for most workloads" [S1]; Fable "when your evals on Claude Opus 5.5 at higher effort still fall short" [S1]; give Fable "root-cause investigations, outage debugging, and architecture decisions" [S8] |

Routing rules this supports [Inferred]:
- R-a: if a role's output is checkable (schema, `cite_check.py`, tests), run it at the tier's low end and re-run failures one level up. This is the measured "`low`, failures re-run at `high`" policy [S12].
- R-b: do not fan out a dependent chain or a task that fits one context. In that case, run the orchestrator model alone at lower effort [S12].
- R-c: set `effort` in each role's frontmatter and never export `CLAUDE_CODE_EFFORT_LEVEL` in kit sessions, because the variable overrides frontmatter [S15].
- R-d: pin full ids in role frontmatter. A same-family alias collapses onto the main session's model [S15].
- R-e: keep Haiku prompts under 100K tokens. Above that, Haiku "pays 5 times as much for each of its tokens, output included" [S12].

Open for R6/R7: the kit currently names Fable 5.1 as orchestrator. Anthropic measured Opus 5.5 at its default "for about a fifth of the cost per solved task" while matching Fable 5.1 [S12]. Whether the owner-facing orchestrator moves to Opus 5.5 is an owner decision.

## 6. Sources (all read 2026-10-16; status = HTTP status of the final URL after redirects)

| ID | URL | HTTP |
|---|---|---|
| S1 | https://platform.claude.com/docs/en/models/overview.md (from docs.anthropic.com/en/docs/about-claude/models/overview) | 200 |
| S2 | https://platform.claude.com/docs/en/about-claude/pricing.md | 200 |
| S3 | https://platform.claude.com/docs/en/models/fable-5-1/overview.md | 200 |
| S4 | https://platform.claude.com/docs/en/models/opus-5-5/overview.md | 200 |
| S5 | https://platform.claude.com/docs/en/models/sonnet-5-5/overview.md | 200 |
| S6 | https://platform.claude.com/docs/en/models/haiku-5-5/overview.md and https://www.anthropic.com/claude-haiku-5-5 | 200 / 200 |
| S7 | https://platform.claude.com/docs/en/about-claude/model-deprecations.md | 200 |
| S8 | https://code.claude.com/docs/en/model-config.md | 200 |
| S9 | https://platform.claude.com/docs/en/build-with-claude/effort.md | 200 |
| S10 | https://platform.claude.com/docs/en/build-with-claude/extended-thinking.md | 200 |
| S11 | https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost.md (the adaptive-thinking URL redirects here) | 200 |
| S12 | https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence.md | 200 |
| S13 | https://www.anthropic.com/claude-fable-and-mythos-5-1 | 200 |
| S14 | https://claude.com/resources/articles/claude-model-and-effort-level-in-claude-code (from claude.com/blog/…) | 200 |
| S15 | https://code.claude.com/docs/en/sub-agents.md | 200 |
| S16 | https://code.claude.com/docs/en/settings-reference.md (and settings.md, 200) | 200 |
| S17 | https://www.anthropic.com/engineering/multi-agent-research-system | 200 |
| M1 | local `claude --help`, Claude Code 2.1.301 | [Measured] |

Also fetched (200) and used only for context: choosing-a-model.md, claude-opus-5-5, claude-sonnet-5-5 and claude.dev/blog/spending-your-effort. No fetch failed.
