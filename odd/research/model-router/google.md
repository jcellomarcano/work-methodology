# Research lane R2: Google Gemini (read 2026-10-16)

Specs S2, S3, S6 of `odd/tasks/model-router.md`. Text inside curly double quotes is verbatim from the cited
source (checked by script against the fetched text, see §7). Tags: [Measured] = local command run on
2026-10-16; [Inferred] = conclusion from cited quotes; [Unknown] = sources silent. Untagged facts come from
the cited official page. Prices are USD per 1M tokens, paid tier, standard rate (no batch/flex/cache)
and **expire**: every price below carries its change date.

## 0. Does Gemini 4 exist? Yes: one model, GA

- Gemini 4 Argon, `gemini-4-argon`, **generally available on 2026-10-13** [S4]: “Gemini 4 Argon
  (gemini-4-argon), our most capable model built for complex coding, agentic, math, and science tasks.”
- The models page lists a “Gemini 4” section with a single model, label “New Stable”, description “Our
  flagship reasoning model with a unified 1M context window and long decodes up to 1M tokens.” [S1]
- It is the only Gemini 4 model. Launch post [S17]: “Gemini 4 Argon is just the beginning. We’re looking
  forward to bringing you the rest of the Gemini 4 family.” No Gemini 4 Flash, Flash-Lite or Pro id
  appears on any fetched page [Measured: the only `gemini-4*` model id in all fetched pages is
  `gemini-4-argon`; other matches are URL slugs]. Later Gemini 4 models are [Unknown].
- The Gemini 4 guide lives at `/gemini-api/docs/latest-model` [S5] (`/whats-new-gemini-4` returns 404).

## 1. Model table (text LLMs that a kit role could use)

| id | status | release | context / max output | price in / out | thinking (default; levels; off?) | struct. out / func. calling | stated strength (verbatim) |
|---|---|---|---|---|---|---|---|
| `gemini-4-argon` | GA (stable) | 2026-10-13 [S4] | 1,048,576 unified in+out; out “65,536 (default synchronous) / up to 1,048,576 (with long decode)” [S6] | $2.00 / $10.00 through 2026-11-30; $4.00 / $20.00 from 2026-12-01; no prompt-size tier; not on Free tier [S2] | medium; low, medium, high; no off or minimal level listed [S3] | yes / yes [S6] | “built for complex software engineering, deep mathematical and scientific problem solving, autonomous multi-step agents, and long decode up to 1M tokens” [S6] |
| `gemini-3.8-flash` | GA (stable) | 2026-09-02 [S4] | 1,048,576 / 65,536 [S7] | $0.75 / $3.75 through 2026-12-31; $1.50 / $7.50 from 2027-01-01 [S2] | medium; low, medium, high; “minimal is not supported and returns an error” [S7] | yes / yes [S7] | “Our most intelligent Flash model, engineered for long-horizon software engineering, autonomous agents, and complex enterprise workflows” [S1] |
| `gemini-3.6-flash` | GA (stable), previous generation | 2026-07-21 [S4] | 1,048,576 / 65,536 [S8] | $0.75 / $3.75 through 2026-12-31; $1.50 / $7.50 from 2027-01-01 [S2] | medium; minimal, low, medium, high [S3] | yes / yes [S8] | “particularly effective for rapid agentic loops involving complex coding cycles and iterations” [S8] |
| `gemini-3.5-flash-lite` | GA (stable) | 2026-07-21 [S4] | 1,048,576 / 65,536 [S9] | $0.30 / $2.50, no date [S2] | minimal; minimal, low, medium, high [S3] | yes / yes [S9] | “optimized for high-throughput, low-cost execution for subagent tasks and document parsing” [S9] |
| `gemini-3.1-flash-lite` | GA; shutdown 2027-05-07 → `gemini-3.5-flash-lite` [S12] | 2026-05-07 [S12] | 1,048,576 / 65,536 [S10] | $0.25 (text/image/video) / $1.50 [S2] | “Supported” [S10]; not in the levels table [S3] → levels [Unknown] | yes / yes [S10] | “optimized for high-frequency, lightweight tasks” [S10] |
| `gemini-3.1-pro-preview` (+ `-customtools`) | Preview; no shutdown date [S12] | 2026-02-19 [S12] | 1,048,576 / 65,536 [S11] | $2.00 / $12.00 prompts ≤200k; $4.00 / $18.00 prompts >200k [S2] | high; low, medium, high [S3] | yes / yes [S11] | “agentic workflows requiring precise tool usage and reliable multi-step execution across real-world domains” [S11] |
| `gemini-2.5-pro`, `-2.5-flash`, `-2.5-flash-lite` | Not deprecated, access limited to past users [S1] | — | 1.0M / 65.5K per pi catalog [Measured] | 2.5 Pro $1.25 / $10.00 ≤200k [S2] | Pro/Flash on, Flash-Lite off by default; low, medium, high [S3] | [Unknown] (spec pages not fetched) | “For any new projects, use our latest models: 3.5 Flash-Lite or 3.8 Flash.” [S1] |

Do not route to: `gemini-3.7-flash`, `gemini-3.5-flash` (deprecated, auto-routed [S4]: “gemini-3.7-flash
is deprecated and has been replaced by gemini-3.8-flash.”); `gemini-3-pro-preview` (shut down 2026-03-09
[S12]); `gemini-3-flash-preview` (preview, replacement `gemini-3.6-flash` [S12]). Out of scope: audio
models (Live, TTS, Transcribe) and agent endpoints (`antigravity-preview-09-2026`, Deep Research) [S1].

Pricing options: “Batch API (50% cost reduction)” [S2]. For Argon and 3.8 Flash, Flex costs the same as
Batch, and Priority costs 1.8× Standard (for example Argon $3.60 / $18.00 through 2026-11-30) [S2].
Output prices include thinking tokens [S2]. Argon caching is “Supported (Implicit only)” [S6]. 3.8 Flash
pricing is unchanged since `multi-provider-routing.md` (2026-09). That doc lists 3.1 Pro preview
as the large-tier candidate; Argon is now GA at a lower output price until 2026-11-30 [Inferred].

## 2. Thinking / effort semantics (Google docs)

- Default behavior [S3]: “Gemini models engage in dynamic thinking by default, automatically adjusting
  the amount of reasoning effort based on the complexity of the request.” The control is
  `thinking_level`. Budgets are legacy [S13]: “Replace thinking_budget with the string enum
  thinking_level.”
- Per-model defaults [S3]: see §1 thinking column; `gemini-2.5-flash-lite` is the only listed model
  whose default is “Off”. No Gemini 3.x or 4 model lists an "off" level, so the cheapest setting is
  `minimal` where it exists, else `low` [Inferred].
- Argon levels [S5]: low “Simpler tasks and cost-sensitive work.” medium (default) “Recommended for
  most tasks, including complex code and agentic use cases.” high “Complex reasoning, hard math and
  science, and the most difficult code or agent tasks.” Method: “Run your evaluations at all three
  levels, then pick the lowest level that meets your quality bar.”
- 3.8 Flash [S13]: “Medium (default): Best quality for most tasks. Recommended for complex code and
  agentic use cases, providing higher first-pass accuracy.” Cost warning: “Gemini 3.8 Flash can use more
  tokens on longer running and complex tasks, by design.” and “For everyday tasks, you can lower the
  reasoning effort to reduce token consumption.”
- 3.5 Flash-Lite [S14]: “For high-volume extraction, routing, or classification: leave thinking_level at
  "minimal" (default) for maximum throughput.” and “For autonomous subagents with tool calls, code
  execution, or multi-step reasoning: set thinking_level to "medium" or "high" to prevent premature tool
  termination.”
- Effort vs. output cap [S3]: “To reduce cost or latency without truncating responses, lower
  thinking_level (low or medium) instead of setting a small max_output_tokens.” Billing: “Pricing is
  based on the full thought tokens the model needs to generate, despite only the summary being output
  from the API.”
- Argon specifics [S5]: “We recommend at least 32,768, since Gemini 4 Argon can spend more of the limit
  on thinking.” and “Increase client timeouts: Hard prompts can take several minutes.” Sampling knobs
  are dead: “Remove temperature, top_p, and top_k from your requests. If provided, they are ignored.”
  Long decode beyond 64K output needs `background=True` [S3].
- General best practice [S3]: “Simple tasks: Use minimal or low thinking for fact retrieval or
  classification” and “Complex tasks: Use maximum thinking for advanced coding, math, or multi-step
  planning”.

## 3. Harness controls

**Gemini CLI.**
- Banner atop every fetched geminicli.com page [S20]: “Gemini CLI has not been optimized for Gemini 4
  Argon. To use Gemini 4 Argon, please use Antigravity.” and “Unpaid tier and Google One users: Gemini
  CLI was replaced by Antigravity CLI on June 18th, 2026.”
- Agent files `.gemini/agents/*.md` (project) or `~/.gemini/agents/*.md` (user), YAML frontmatter
  [S18]; keys `name`, `description`, `kind`, `tools`, `mcpServers`, `model`, `temperature`,
  `max_turns`, `timeout_mins`. `model`: “Defaults to inherit (uses the main session model).”
  `max_turns`: “Maximum number of conversation turns allowed for this agent before it must return.
  Defaults to 30.” `timeout_mins`: “Maximum execution time in minutes. Defaults to 10.” **No thinking
  key** in the frontmatter.
- `settings.json` overrides [S18]: `agents.overrides.<name>.runConfig` (`maxTurns`, `maxTimeMinutes`)
  and `.modelConfig.model`; `modelConfigs.overrides`: “You can target specific subagents with custom
  model settings (like system instruction prefixes or specific safety settings) using the overrideScope
  field.” The config reference defines `generateContentConfig.thinkingConfig.thinkingLevel`; its
  built-in `chat-base-3` alias sets `"HIGH"`, above the API default medium [S20]. Per-subagent
  thinking = `modelConfigs.overrides` + `match.overrideScope` + `thinkingConfig.thinkingLevel`
  [Inferred: two documented features combined; not run].
- Selecting a model:
  - Per subagent [S19]: “The /model command (and the --model flag) does not override the model used by
    sub-agents.” So set `model:` in each agent file.
  - Main session precedence [S21]: `--model` > `GEMINI_MODEL` > `model.name` in settings > local Gemma
    router > “The default model is auto”.
- Isolation [S18]: “subagents cannot call other subagents”. This matches the kit's `may_spawn: []`.
  `temperature` is still a key but is ignored by 3.6+/4 models (§2) [Inferred].
- Local `gemini` [Measured]: `gemini --version` → `0.63.0`; `gemini --help` model flag
  `-m, --model  Model  [string]`, no thinking/effort flag; also `-p/--prompt` (headless),
  `--skip-trust`, `--approval-mode default|auto_edit|yolo|plan`, `-o/--output-format text|json|stream-json`.
- Stale docs: `/model` docs (2026-03-19) still list `gemini-3-pro-preview` under “Auto (Gemini 3)”
  [S19], shut down per [S12]. The thinking guide's sample uses `gemini-3.8-pro`, an id absent from the
  models page [S1, S3]; do not use it.

**Managed agents (Antigravity, API).**
- The Antigravity agent is a “General-purpose managed agent built with Gemini 3.8 Flash.” [S15]
- “Supported model options in agent_config are gemini-3.8-flash (default), gemini-3.6-flash, and
  gemini-3.5-flash-lite.” and “No subagent nesting: Subagent delegation is not yet supported.” [S16]
- The Argon guide [S5] says the Antigravity agent accepts `agent_config.model = "gemini-4-argon"`.
  [S16] and [S5] disagree [Unknown: which is current].

**pi** [Measured, `pi --version` 1.3.0, `pi --list-models gemini`, 2026-10-16]:
- 19 `google/*` ids, including `gemini-4-argon` (1.0M ctx, **32.8K max-out**), `gemini-3.8-flash`,
  `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.1-pro-preview(-customtools)`,
  `gemini-flash-latest`, `gemini-flash-lite-latest`; also the deprecated or shut-down `gemini-3.7-flash`,
  `gemini-3.5-flash`, `gemini-3.1-flash-lite-preview`, `gemini-2.5-computer-use-preview-10-2025`.
- Selection: `--model google/<id>[:<thinking>]` or `--thinking off|minimal|low|medium|high|xhigh|max`.
- How pi maps `off`, `xhigh` and `max` onto Google's `thinking_level` is [Unknown]. Argon has no
  off/minimal level. pi's 32.8K max-out for Argon differs from Google's 65,536 [S6]: treat pi's
  catalog as unverified.

## 4. Google guidance on agentic / multi-agent use and Flash vs Pro vs Flash-Lite

- Flash vs Flash-Lite [S14]: Flash-Lite primary use cases “Autonomous subagent execution, high-volume
  data analysis and document extraction, structured JSON parsing”; 3.6 Flash “Code generation,
  spatial/multimodal reasoning, multi-step agentic workflows”; and “Increase the thinking level for
  autonomous planning and complex subagent tasks.”
- Pro vs Flash (Gemini CLI) [S19]: “Use Pro models for complex tasks and reasoning, Flash models for high
  speed results”, “Switch to Pro if you aren't getting the results you want.”, “Switch to Flash or
  Flash-Lite if you need faster results.”
- Isolation [S18]: “Independent context window: Interactions with a subagent happen in a separate context
  loop, which saves tokens in your main conversation history.”
- Argon [S17]: “Argon excels at deep work in complex, real-world tasks across domains including coding,
  finance, legal, cybersecurity, and science.” [S22]: “Gemini 4 Argon is designed for those
  long-horizon workflows that require deep reasoning and structural precision, including code
  migrations and frontier research.”
- 3.1 Pro preview custom-tools endpoint [S11]: “This endpoint is better at prioritizing your custom
  tools (for example view_file or search_code).”
- Google publishes no Pro model newer than 3.1 Pro preview; Argon fills the flagship slot [Inferred from
  S1].

## 5. Tier mapping proposal for the kit [Inferred; admission test of `multi-provider-routing.md` §4 still required]

| Kit tier | Gemini model | Effort | Justification (cited) |
|---|---|---|---|
| small: rulebook / JSON verdict (style-reviewer, comment-gate) | `gemini-3.5-flash-lite` | `minimal` | “For high-volume extraction, routing, or classification: leave thinking_level at "minimal" (default) for maximum throughput.” [S14] |
| small: acts with tools (mechanic) | `gemini-3.5-flash-lite` | `medium` | “For autonomous subagents with tool calls, code execution, or multi-step reasoning: set thinking_level to "medium" or "high" to prevent premature tool termination.” [S14] |
| medium, read-and-report (cartographer, verifier) | `gemini-3.8-flash` | `low`, raise to `medium` on miss | “For everyday tasks, you can lower the reasoning effort to reduce token consumption.” [S13]; `minimal` errors on 3.8 Flash [S7] |
| medium: reasons about code (proposer, judge with no P0, boundary-reviewer) | `gemini-3.8-flash` | `medium` | “Medium (default): Best quality for most tasks. Recommended for complex code and agentic use cases, providing higher first-pass accuracy.” [S13] |
| large (challenger, blind-spot adversary, judge on P0 or critical property) | `gemini-4-argon` | `high` | high = “Complex reasoning, hard math and science, and the most difficult code or agent tasks.” [S5]; GA, unlike preview `gemini-3.1-pro-preview` [S12] |
| orchestrator / voice to the owner | stays on the incumbent (kit doc `00-principles/multi-provider-routing.md`: "not swapped for cost"); if Gemini, `gemini-4-argon` at `medium` | `medium` | “Recommended for most tasks, including complex code and agentic use cases.” [S5]. Gemini CLI is not optimized for Argon [S20], so an Argon orchestrator needs Antigravity or the API, not Gemini CLI |

Caveats [Inferred]: Argon doubles price on 2026-12-01 ($4 / $20 [S2]) and the Flash tiers on
2027-01-01, so the router must read prices with a date. Pick the lowest level that passes (Google's own
method [S5]). In Gemini CLI set effort per subagent through `modelConfigs.overrides`; the frontmatter
has no thinking key [S18].

## 6. Sources (all read 2026-10-16, HTTP status as fetched with `curl -sL`)

| id | URL | HTTP | page date |
|---|---|---|---|
| S1 | https://ai.google.dev/gemini-api/docs/models | 200 | 2026-10-13 |
| S2 | https://ai.google.dev/gemini-api/docs/pricing | 200 | 2026-10-15 |
| S3 | https://ai.google.dev/gemini-api/docs/thinking | 200 | 2026-10-14 |
| S4 | https://ai.google.dev/gemini-api/docs/changelog | 200 | 2026-10-14 |
| S5 | https://ai.google.dev/gemini-api/docs/latest-model ("What's new in Gemini 4 Argon") | 200 | 2026-10-13 |
| S6 | https://ai.google.dev/gemini-api/docs/models/gemini-4-argon | 200 | 2026-10-14 |
| S7 | https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash | 200 | 2026-09-02 |
| S8 | https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash | 200 | 2026-07-30 |
| S9 | https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite | 200 | 2026-07-30 |
| S10 | https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite | 200 | 2026-07-21 |
| S11 | https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview | 200 | 2026-10-09 |
| S12 | https://ai.google.dev/gemini-api/docs/deprecations | 200 | — |
| S13 | https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.8 | 200 | — |
| S14 | https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.6 | 200 | — |
| S15 | https://ai.google.dev/gemini-api/docs/agents | 200 | — |
| S16 | https://ai.google.dev/gemini-api/docs/custom-agents | 200 | — |
| S17 | https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-4-argon/ | 200 | 2026-10-13 |
| S18 | https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/core/subagents.md (same table on https://geminicli.com/docs/core/subagents/, 200) | 200 | — |
| S19 | https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/cli/model.md (= https://geminicli.com/docs/cli/model/, 200) | 200 | 2026-03-19 |
| S20 | https://geminicli.com/docs/reference/configuration/ | 200 | 2026-10-15 |
| S21 | https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/cli/model-routing.md | 200 | — |
| S22 | https://blog.google/innovation-and-ai/technology/developers-tools/build-with-gemini-4-argon/ | 200 | 2026-10-13 |

Failed fetch: https://ai.google.dev/gemini-api/docs/whats-new-gemini-4 → 404 (guessed URL; the guide is
S5). Vertex AI pages were not needed and not fetched.

## 7. Verification

Quote check (2026-10-16): a script extracted every curly-double-quoted span in this file and searched
for each one in the fetched text of S1-S22, after normalizing whitespace, curly apostrophes, and
markdown `*`/`` ` ``. Result: 66/66 quotes found, 0 missing. The 20 price strings behind §1 and its pricing note were
matched literally against S2: 20/20 found. Fetched pages were kept only under `$TMPDIR`, never in the repo.
