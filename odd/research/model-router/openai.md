# Research R3: OpenAI GPT models and effort routing (read 2026-10-16)

Lane R3 of `odd/tasks/model-router.md` (S2, S3). Tags: **[M]** measured (read on the fetched page cited as S#, or seen in a local command L#), **[I]** inferred, **[A]** assumed, **[U]** unknown. Text in double quotes is verbatim. Prices are USD per 1M tokens, Standard tier, prompts up to 272K input tokens, read 2026-10-16; they expire.

## 1. Model map (coding and agentic text models)

| Model id (aliases) | Status | Released | Context / max input | Max out | In / cached / out | `reasoning.effort` (default) | Strengths (verbatim) | Deprecation |
|---|---|---|---|---|---|---|---|---|
| `gpt-6-astra` (snapshot `gpt-6-astra`) | flagship, current [M S1] | 2026-09-03 [M S4] | 1,050,000 / 922,000 | 128,000 | $10 / $1 / $50; cache write $12.5 | low, medium, high, xhigh, max; API default not stated [U]; Codex catalog default `low` [M L1] | "Our most capable model for the most demanding work." | none listed [M S5] |
| `gpt-6.1-sol` (snapshot `gpt-6.1-sol`) | current, balanced [M S1] | 2026-09-29 [M S4] | 1,050,000 / 922,000 | 128,000 | $2 / $0.10 / $10; cache write $2.5 | low, medium (default), high, xhigh, max; "The `none` and `minimal` reasoning efforts are not supported." | "Near-Astra performance for complex work at a lower cost." | none listed |
| `gpt-6-sol` | superseded: "See [GPT-6.1 Sol](/api/docs/models/gpt-6.1-sol) for the newer Sol model." | 2026-09-22 [M S4] | 1,050,000 / 922,000 | 128,000 | $2 / $0.20 / $10 | none, low, medium (default), high, xhigh, max | "Built to power complex coding and agentic workflows." | none listed |
| `gpt-6-luna` | current, efficient [M S1] | 2026-09-22 [M S4] | 1,050,000 / 922,000 | 128,000 | $0.10 / $0.01 / $0.50 | none, low, medium (default), high, xhigh, max | "Our most efficient model for focused, high-volume tasks." | none listed |
| `gpt-5.6-sol` (alias `gpt-5.6`) | previous generation, available | 2026-07-09 [M S4] | 1,050,000 / 922,000 | 128,000 | $4 / $0.40 / $20 (promo) | none, low, medium (default), high, xhigh, max | "GPT-5.6 flagship model for complex professional work" | none; promo "available at least through November 21, 2026" |
| `gpt-5.6-terra` | previous generation | 2026-07-09 | 1,050,000 / 922,000 | 128,000 | $2 / $0.20 / $12 | none … max (medium) | "GPT-5.6 model that balances intelligence and cost" | none listed |
| `gpt-5.6-luna` | previous generation | 2026-07-09 | 1,050,000 / 922,000 | 128,000 | $0.20 / $0.02 / $1.20 | none … max (medium) | "GPT-5.6 model optimized for cost-sensitive workloads" | none listed |
| `gpt-5.5` (snapshot `gpt-5.5-2026-04-23`) | previous; retired from Codex with ChatGPT sign-in [M S11] | 2026-04-24 [M S4] | 1,050,000 | 128,000 | $5 / $0.50 / $30 | none, low, medium (default), high, xhigh | "A new class of intelligence for coding and professional work." | Codex sign-in: "Effective October 14, 2026"; API unaffected |
| `gpt-5.3-codex` | deprecated 2026-10-01 [M S5] | 2026-02-24 [M S4] | 400,000 / 272,000 | 128,000 | $1.75 / $0.175 / $14 | low, medium, high, xhigh | "The most capable agentic coding model to date." (catalog blurb, pre-GPT-6) | shutdown Apr 1, 2027 → `gpt-6-sol` |
| `codex-mini-latest` | legacy | [U] | 200,000 | 100,000 | $1.5 / $0.375 / $6 | not stated [U] | "a fine-tuned version of o4-mini" | [U] |

Common to the four GPT-6 models [M S2]: text+image in, text out; features `structured_outputs`, `function_calling`, `prompt_caching`, streaming; Responses tools `web_search`, `file_search`, `image_generation`, `code_interpreter`, `hosted_shell`, `apply_patch`, `skills`, `computer_use`, `mcp`, `tool_search`. Tool calling: "Use the Responses API for tool calling. Chat Completions is supported without tool calling." (6.1 Sol); for 6 Sol and 6 Luna "Chat Completions supports function calling only with `reasoning_effort` set to `none`."

Price modifiers [M S2, S3]: "Prompts with more than 272K input tokens are priced at 2x input and cache rates and 1.5x output for the full request." "Batch and Flex are priced at 50% of Standard rates. Fast mode is priced at 2x the applicable rates." For 6.1 Sol: "Ultrafast mode prices are 6x Standard." Ratios [I]: Astra costs 5x 6.1 Sol per token; 6.1 Sol costs 20x 6-Luna.

Out of scope here: `gpt-5.6-cyber` and the Daybreak aliases (gated security access), `gpt-oss-*` (lane R4, local), Pro model ids and `reasoning.mode: "pro"` (see §2).

**Verbosity.** API field `text.verbosity`: "Currently supported values are `low`, `medium`, and `high`. The default is `medium`." [M S9]. No model page lists per-model verbosity support [U]. Codex key `model_verbosity` (`low | medium | high`) [M S12]; the local Codex catalog sets `default_verbosity` `low` for `gpt-6-astra` and the GPT-5.6 models [M L1].

**Correction to the kit.** `00-principles/multi-provider-routing.md` (read 15-sep-2026) prices GPT-5.6 Sol at $5/$30 from a secondary page and gives Terra "reasoning low…ultra". Official today: Sol $4/$20 promo, Terra `none`…`max`; `ultra` is a Codex-only level (§3), not an API value [M S2, S8, S12].

## 2. Effort semantics (OpenAI, verbatim)

General [M S8]: "Lower effort favors speed and lower token usage, while at higher effort the model thinks more completely to provide higher quality responses. The models also reason adaptively across reasoning efforts, using fewer tokens for simpler tasks and thinking harder for complex tasks." Reasoning tokens "are billed as [output tokens]" (S8), so effort mostly changes output spend [I].

| Effort | What OpenAI says it is for [M S8 unless noted] |
|---|---|
| `none` | "Latency-critical tasks that do not benefit from any reasoning or multi-chained tool calls." Not on Astra or 6.1 Sol: "Setting `reasoning.effort` (Responses) or `reasoning_effort` (Chat Completions) to `none` returns HTTP 400." |
| `minimal` | Listed as a possible value; no GPT-6 or GPT-5.6 page supports it [M S2]. Migration: "If your existing request uses `minimal`, start with `low` and compare results on representative tasks." [M S6] |
| `low` | "Efficient reasoning with a modest latency increase. Ideal for use cases requiring tool-use, planning, search, or multi-step decision making, while optimizing for speed and cost." Uses include "execution-oriented coding". |
| `medium` | "When quality and reliability matter, and the task involves planning, complex reasoning, and judgement. Default configuration for most workloads, and a well-balanced point on the pareto curve of latency, performance and cost." |
| `high` | "Hard reasoning, complex debugging, deep planning, and high-value tasks where quality and intelligence matters more than latency." "Depending on the complexity of the task, evaluate both `medium` and `high`." |
| `xhigh` | "Only use when your evals show a clear benefit that justifies the extra latency and cost." Uses include "security and code review". |
| `max` | "Maximum reasoning for your most complex tasks. If you are currently using `xhigh`, evaluate if `max` results in stronger performance" |
| `ultra` (Codex only) | Catalog text: "Maximum reasoning with automatic task delegation" [M L1]. Docs: "Most tasks do not need Max or Ultra." and "GPT-6 Luna supports reasoning efforts up to **Max**, but not **Ultra**." [M S11] |

Related knobs [M S8]: `reasoning.mode` `standard` (default) or `pro`: "Reasoning mode and reasoning effort are independent." Pro "performs more model work than standard mode, increasing token usage and cost." Mid-conversation change: "Use `configuration_update` to increase reasoning effort for difficult work or reduce it for routine follow-ups." Scope: "Configuration updates are supported by the GPT-6 model family in standard, single-agent mode." OpenAI also warns: "Treat `reasoning.effort` as a tuning knob, not the primary way to recover quality." Effort names do not carry across generations: "Reasoning efforts don't map exactly between model generations." [M S11]

OpenAI's model x effort ladder [M S7]: "Luna · Low" for "Fine-grained edits, well-scoped problem-solving, and simple data extraction."; "Luna · Extra high" for "solving problems with clear constraints"; "GPT-6.1 Sol · Medium" for "Complex technical work and coordinated deliverables you expect to revise."; "GPT-6.1 Sol · Extra high" for "decisions built from conflicting evidence"; "Astra · Medium" for "Ambitious projects that need broad context, reliable interactions, and complete results."; "Astra · Extra high" for "Demanding analysis and complex deliverables with exacting requirements." Rule: "keep the lightest setting that meets your quality bar."

## 3. Harness controls

**Codex CLI** (docs S11-S14; local `codex-cli 0.154.0` L1).

| Scope | Exact control |
|---|---|
| per session | `codex --model gpt-6.1-sol`, `codex exec -m gpt-6.1-sol "..."` [M S11]; any key via `-c`/`--config`, value parsed as TOML, e.g. `codex --config model='"gpt-6.1-sol"'` [M S13]; effort the same way, `-c model_reasoning_effort='"high"'` [I from the generic `-c` rule]. Interactive: `/model`, then "More reasoning…" for Max/Ultra [M S11]. |
| config keys | `model`; `model_reasoning_effort` ("such as `low`, `medium`, `high`, `xhigh`, `max`, or `ultra`. Available levels depend on the model and client."); `plan_mode_reasoning_effort`; `model_reasoning_summary`; `model_verbosity`; `service_tier` (`fast` …) [M S12] |
| profile | file `~/.codex/<name>.config.toml` with top-level keys, selected by `--profile <name>` / `-p`; "In Codex 0.134.0 and later, `--profile` no longer reads `[profiles.profile-name]`" [M S13, L1] |
| all subagents | `[agents]`: `enabled`, `max_concurrent_threads_per_session` (legacy alias `max_threads`), `default_subagent_model`, `default_subagent_reasoning_effort`, `interrupt_message`; per role `agents.<name>.description`, `agents.<name>.config_file` [M S12]. No `max_depth` key in today's reference [M S12]. |
| one agent | `~/.codex/agents/*.toml` or `.codex/agents/*.toml`; required `name`, `description`, `developer_instructions`; optional `model`, `model_reasoning_effort`, `model_reasoning_summary`, `model_verbosity` [M S14] |

Precedence [M S14]: "If a custom agent file sets `model` or `model_reasoning_effort`, the value in the file takes precedence." Otherwise "Codex resolves each setting from an explicit spawn value, then the corresponding `[agents]` default, then the parent's value." Unset means inherit: "the subagent inherits the parent agent's model and reasoning effort." Limits that contradict the kit's §3 table (which lists sandbox and `mcp_servers` per agent): "They inherit the parent's permissions, provider, and MCP servers; a custom agent file can't override those settings." and "Other session settings, including `sandbox_mode`, `approval_policy`, `model_provider`, and `mcp_servers`, don't override the parent configuration when placed in a custom agent file." Read-only roles cannot be enforced per agent: "Custom agent instructions can ask an agent to avoid edits, but they don't create a separate read-only sandbox." Delegation is not automatic: "Current local Codex releases spawn agents after a direct request or applicable project or skill instruction."

Local measurement [M L1]: `codex debug models` (refreshed and `--bundled`) lists `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.2`, and hidden `gpt-5.4`, `gpt-5.4-mini`, `codex-auto-review`. It has **no** `gpt-6.1-sol`, `gpt-6-sol` or `gpt-6-luna` entries even though the docs recommend them; for this binary they are [U] until a run proves it. Catalog effort lists: Astra/5.6 Sol/5.6 Terra `low`…`ultra`, 5.6 Luna `low`…`max`, 5.5 `low`…`xhigh`. Catalog `context_window` 272000 and `max_context_window` 872000 for Astra and 5.6 (API page: 1,050,000).

**OpenAI API** [M S8, S9, S17]: `reasoning.effort`, `reasoning.mode`, `reasoning.context`, `text.verbosity`, `max_output_tokens`; `configuration_update` input item. Hosted Multi-agent: `multi_agent.enabled`, beta "with [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and all GPT-5.6 models"; "The subagents share the request’s model and available tools", so per-role models need your own orchestrator or the Agents SDK [I].

**pi** (`pi 1.3.0`, L2) [M]: `--model <pattern>` help text: `Model pattern or ID (supports "provider/id" and optional ":<thinking>")`; thinking levels "off, minimal, low, medium, high, xhigh, max". OpenAI models appear under provider `openai-codex` (ChatGPT sign-in): `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6-sol`, `gpt-6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`; context 272K (500K for `gpt-6.1-sol`), max-out 128K. Example: `pi --model openai-codex/gpt-6.1-sol:high`. pi has no `ultra`; how `off`/`minimal` map onto OpenAI `none` and onto models that reject them is [U]; no `openai` (API-key) provider was listed on this machine.

## 4. OpenAI guidance on single- vs multi-agent (verbatim)

- Start single [M S19]: "Our general recommendation is to maximize a single agent’s capabilities first. More agents can provide intuitive separation of concepts, but can introduce additional complexity and overhead, so often a single agent with tools is sufficient."
- When to split [M S19]: "When your agents fail to follow complicated instructions or consistently select incorrect tools, you may need to further divide your system and introduce more distinct agents." Triggers: "Complex logic" and "Tool overload": "The issue isn’t solely the number of tools, but their similarity or overlap."
- Patterns [M S19]: "Manager (agents as tools)": "A central “manager” agent coordinates multiple specialized agents via tool calls, each handling a specific task or domain." "Decentralized (agents handing off to agents)": "Multiple agents operate as peers, handing off tasks to one another based on their specializations." Manager "is ideal for workflows where you only want one agent to control workflow execution and have access to the user." Decentralized "is optimal when you don’t need a single agent maintaining central control or synthesis".
- Model choice [M S19]: "build your agent prototype with the most capable model for every task to establish a performance baseline. From there, try swapping in smaller models to see if they still achieve acceptable results." and "Not every task requires the smartest model".
- Agents SDK [M S16]: "Start with one agent whenever you can. Add specialists only when they materially improve capability isolation, policy isolation, prompt clarity, or trace legibility." "Splitting too early creates more prompts, more traces, and more approval surfaces without necessarily making the workflow better." Agents as tools fit when "the specialist is doing a bounded task like summarization or classification".
- Responses Multi-agent [M S17]: "Note that adding subagents can increase token usage, and may not be as beneficial for tasks that depend on a single ordered chain of reasoning, require frequent writes to shared mutable state, or are already dominated by one slow external operation." Prefer one agent when "Each step depends directly on the previous step" or "You require a fixed, deterministic execution graph".
- Agents API [M S18]: "Keep short tasks and dependent steps in the main agent. Agents that edit the same files must coordinate their changes."
- Codex [M S14]: "use parallel agents for read-heavy tasks such as exploration, tests, triage, and summarization. Be more careful with parallel write-heavy workflows". Cost: "subagent workflows consume more tokens than comparable single-agent runs". Shape: "The best custom agents are narrow and opinionated."
- GPT-6 Astra [M S6]: "The model may delegate less often than desired for your workflow. Specify when and how much it should use subagents for parallel work."
- Planner and doer [M S20, older o-series guide]: "We’ve seen success when a reasoning model is used as “the planner,” producing a detailed, multistep solution to a problem and then selecting and assigning the right GPT model (“the doer”) for each step".

## 5. Tier mapping proposal for the kit [I]

All entries are `status: candidate` until the admission test in `multi-provider-routing.md` §4 passes (n = 2, same brief). Kit context caps stay under 272K, so the long-context surcharge does not apply [I].

| Kit tier / role | OpenAI model : effort | Why (cited quote) |
|---|---|---|
| small: style-reviewer, comment-gate, human-reviewer | `gpt-6-luna` : `low` | S7 "Luna · Low" for "simple data extraction"; S11 Luna "when you know what a good result looks like, such as extraction, classification, transformation, and structured summaries." |
| small: mechanic (edits) | `gpt-6-luna` : `high` | S14 example `ui_fixer` uses `gpt-6-luna` with `high` and asks to "Make the smallest defensible change"; S14 "start with `high` for GPT-6 Luna". |
| medium: cartographer | `gpt-6-luna` : `high` | S14 `pr_explorer`: "Read-only codebase explorer for gathering evidence before changes are proposed." on Luna `high`. |
| medium: verifier, boundary-reviewer, judge (no P0) | `gpt-6.1-sol` : `medium` | S14 `reviewer` ("correctness, security, and missing tests") on `gpt-6.1-sol` `medium`; S8 medium "involves planning, complex reasoning, and judgement". |
| medium: proposer | `gpt-6.1-sol` : `medium`, escalate to `high` | S7 "GPT-6.1 Sol · Medium" for "Complex technical work and coordinated deliverables you expect to revise."; S8 "evaluate both `medium` and `high`". |
| large: challenger, blind-spot adversary, judge with P0 | `gpt-6-astra` : `high`; cheaper trial `gpt-6.1-sol` : `xhigh` | S11 Astra "for the hardest end-to-end work"; S14 `high` "for example, reviewer or security-focused agents"; S8 xhigh uses include "security and code review". |
| orchestrator / voice to owner | `gpt-6-astra` : `medium` (`low` for routine turns) | S7 "Astra · Medium" for "Ambitious projects that need broad context"; S11 "Astra is better at asking focused questions"; S14 "For explicit model settings, start with `high` for GPT-6 Luna or `low` for GPT-6 Astra." |
| escalation after two stalls | raise one effort step, not one model step, first; `max` only on eval evidence | S8 "Treat `reasoning.effort` as a tuning knob, not the primary way to recover quality." and the `max` row. |
| never inside a kit role | `ultra`, API `multi_agent.enabled`, `reasoning.mode: pro` | kit roles have `may_spawn: []`; `ultra` is "Maximum reasoning with automatic task delegation" [M L1]; pro "increasing token usage and cost" [M S8]. |

Harness consequences [I]: (1) in Codex, set `model` and `model_reasoning_effort` in every `.codex/agents/<role>.toml`, because unset values inherit the parent (S14); (2) sandbox, approvals and MCP come from the parent session, so a read-only role needs a read-only parent session or the kit's own checks, not the agent file (S14); (3) with this local Codex build, prefer `gpt-6-astra` and `gpt-5.6-terra` / `gpt-5.6-luna` until `gpt-6.1-sol` and `gpt-6-luna` appear in `codex debug models` (L1); (4) GPT-6 Astra needs explicit delegation prompts (S6), which matches the kit's rule that the orchestrator, not the model, decides the roster.

## 6. Sources (all read 2026-10-16)

| ID | URL | HTTP |
|---|---|---|
| S1 | https://developers.openai.com/api/docs/models (also `.md`); https://platform.openai.com/docs/models redirects here | 200 |
| S2 | https://developers.openai.com/api/docs/models/{gpt-6-astra, gpt-6.1-sol, gpt-6-sol, gpt-6-luna, gpt-5.6-sol, gpt-5.6-terra, gpt-5.6-luna, gpt-5.5, gpt-5.3-codex, codex-mini-latest}.md | 200 each |
| S3 | https://developers.openai.com/api/docs/pricing.md | 200 |
| S4 | https://developers.openai.com/api/docs/changelog.md | 200 |
| S5 | https://developers.openai.com/api/docs/deprecations.md | 200 |
| S6 | https://developers.openai.com/api/docs/guides/latest-model.md ("Using GPT-6") | 200 |
| S7 | https://developers.openai.com/api/docs/guides/model-selection.md | 200 |
| S8 | https://developers.openai.com/api/docs/guides/reasoning.md | 200 |
| S9 | https://developers.openai.com/api/reference/resources/responses/methods/create.md | 200 |
| S10 | https://developers.openai.com/api/docs/guides/code-generation.md (Codex "works best with the latest general-purpose models") | 200 |
| S11 | https://learn.chatgpt.com/docs/models.md (https://developers.openai.com/codex/models redirects here) | 200 |
| S12 | https://learn.chatgpt.com/docs/config-file/config-reference.md | 200 |
| S13 | https://learn.chatgpt.com/docs/config-file/config-advanced.md | 200 |
| S14 | https://learn.chatgpt.com/docs/agent-configuration/subagents.md | 200 |
| S15 | https://learn.chatgpt.com/docs/agent-configuration/speed.md (Fast/Ultrafast) | 200 |
| S16 | https://developers.openai.com/api/docs/guides/agents/orchestration.md | 200 |
| S17 | https://developers.openai.com/api/docs/guides/responses-multi-agent.md | 200 |
| S18 | https://developers.openai.com/api/docs/guides/agents-api/multi-agent.md | 200 |
| S19 | https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf | 200 |
| S20 | https://developers.openai.com/api/docs/guides/reasoning-best-practices.md | 200 |
| L1 | local `codex-cli 0.154.0`: `codex --help`, `codex exec --help`, `codex debug models`, `codex debug models --bundled` | n/a |
| L2 | local `pi 1.3.0`: `pi --help`, `pi --list-models gpt-6`, `pi --list-models gpt-5.6` | n/a |

Failed fetches: https://openai.com/api/pricing/ 403; https://openai.com/business/guides-and-resources/a-practical-guide-to-building-agents/ 403 (PDF S19 used instead); https://openai.com/index/gpt-6-astra/ 403; https://developers.openai.com/api/docs/guides/multi-agent 404. No secondary (third-party) source used.
