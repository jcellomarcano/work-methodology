# Multi-provider routing: the same roles, any model admitted by measurement

Extends `model-routing.md`: that document decides **what kind of intelligence** each role needs;
this one decides **which models from which provider** can occupy each tier once they're available in the
project's harness, and **how they get admitted**. Governing rule: a model doesn't enter a role on its
marketing sheet but on a test measured with the same briefs, schemas, and scripts the role already uses.
Cap: 80 lines. Machine-readable configuration: `03-tools/config/model-tiers.json`. Sources and dates at
the end; prices expire, the rule doesn't.

## 1. Tiers, not models

| Tier | Context cap | Kit roles | Today's incumbent (Claude Code) | Candidates per provider (2026-09) |
|---|---|---|---|---|
| small | 15k | style-reviewer, comment-gate, human-reviewer, mechanic | Claude Haiku 4.5 (`claude-haiku-4-5`, 200K, $1/$5) | Gemini 3.5 Flash-Lite ($0.30/$2.50) · Gemini 3.8 Flash ($0.75/$3.75 through Dec-31-2026; $1.50/$7.50 after) · GPT-5.6 Luna (`gpt-5.6-luna`, $0.20/$1.20, 1.05M, 128k output) |
| medium | 30-60k | cartographer, verifier, boundary-reviewer, judge (no P0), proposer | Claude Sonnet 5 (`claude-sonnet-5`, 1M, $2/$10) | Gemini 3.8 Flash (1M input, 65k output; structured output, function calling, thinking low/medium/high) · GPT-5.6 Terra (`gpt-5.6-terra`, $2/$12, $4/$18 in long context; 1.05M, 128k output, reasoning low…ultra) |
| large | 60k | challenger, blind-spot adversary, judge with a P0 or a critical property | Claude Opus 5 (`claude-opus-5`, 1M, $5/$25) | Gemini 3.1 Pro preview ($2/$12 ≤200k; $4/$18 >200k) · GPT-5.6 Sol (`gpt-5.6-sol`, $5/$30; the `gpt-5.6` alias routes to Sol) |
| orchestrator and voice to the owner | < 150k per session | whoever designs, decides, and talks | Claude Fable 5.1 (`claude-fable-5-1`, 1M, $10/$50) | not swapped for cost; the response identity already has adapters `07-communication/adapters/` |

Prices per million input/output tokens, standard rate, no batch or cache. "Medium" doesn't exist as a
model in the Gemini lineup published 04-sep-2026 (Flash-Lite, Flash, Pro): when the owner says "medium"
they mean this table's medium tier.

## 2. Which role can move first, and why

- **First, roles that interpret against a fixed rulebook** (small tier): the output is a JSON verdict against a schema and a closed rulebook (DOC-001, KS-00x, COM-xx). A Flash-Lite or a nano costs 4-5 times less than Haiku and the error surfaces via the schema itself. Candidates: comment-gate and style-reviewer; the mechanic later, because it edits.
- **Then the cartographer and the verifier** (medium tier): they read and report with `file:line`, `cite_check.py` measures their accuracy without human judgment. Data from the origin project: two cartographers on Sonnet spent 96k and 110k tokens (≈ $0.25 each); on Gemini 3.8 Flash the same brief would cost ≈ $0.10 [Inferred from price, not measured].
- **The proposer stays on Claude** until a trial on a low-risk unit disproves it: it writes Kotlin, runs Gradle via scripts, and its diff gets attacked by two adversaries; the cost of it failing is a whole round.
- **The large adversaries**: the rule of two adversaries WINS with heterogeneity. A third adversary from another provider, on trial, hunts the blind spots two models from the same house share. Its findings reach the judge tagged `trial`; it doesn't replace the incumbent pair in critical flow without the owner's decision.

## 3. Harness requirements per provider (what the methodology needs, not what the CLI promises)

| Kit need | Claude Code | Gemini CLI | Codex CLI |
|---|---|---|---|
| per-role agent definition | `.claude/agents/<role>.md` (frontmatter `model`, `tools`, `maxTurns`, hooks) | `.gemini/agents/<role>.md` (YAML: `name`, `description`, `model`, `tools` with `mcp_*` wildcards, `mcpServers`, `max_turns`=30, `timeout_mins`=10, `temperature`) | `~/.codex/agents/*.toml` or `.codex/agents/` (`name`, `description`, `developer_instructions`, `model`, reasoning, sandbox, `mcp_servers`; `[agents]` `max_threads`=6, `max_depth`=1) |
| typed `mcp__metodo__*` tools | `.mcp.json` | inline `mcpServers` per agent | `mcp_servers` per agent |
| isolated context per agent | yes | yes ("independent context window") | yes (threads) |
| call budget | `budget.py` hook (deterministic) | `max_turns` + `timeout_mins` [Assumed equivalent] | to be verified [Unknown] |
| output validation on close | `validate_subagent_output.py` hook | none: done by the orchestrator with `lib/round_output.py` | same |
| handoff via numbered file | `output_write` / `round_output.py` | same (it's a script) | same |

A per-harness installer (`bin/install-claude.sh` today; `install-gemini.sh` and `install-codex.sh` pending) generates the definitions from `01-roles/agents/` and `model-tiers.json`; the kit stays the source of truth.

## 4. Protocol for admitting a model into a role (without this, `status: candidate`)

1. **Same brief, same round**: the candidate runs the exact brief the incumbent ran (e.g. a cartographer on the same unit), with the same `000-context.md` and the same INPUTS; never an "adapted" brief.
2. **Schema**: the output passes `lib/round_output.py` (PASS or it doesn't count).
3. **Evidence accuracy**: `lib/cite_check.py --repo` over the `file:line@sha` citations; the rate of citations that exist must be ≥ the incumbent's on the same run.
4. **Blind judgment**: the kit's judge rules on both candidates' claims or findings without knowing who's who; the CONFIRMED rate and the BROKENs only one of them found get compared.
5. **Cost and tokens** logged in `runs/`; minimum **n = 2** runs (precedent: the kit's brief experiment). Result in `model-tiers.json` (`admitted`, `rejected`, with a date and minutes in `minutes/`). A critical-lane role (money, security, recoverability) also requires the owner's OK even if the test passes.

## 5. Sources (read 15-sep-2026)

- Google, "Gemini models" (page dated 2026-09-04): 3.8/3.7/3.6/3.5 Flash lineup, 3.5/3.1 Flash-Lite, 3.1 Pro preview. https://ai.google.dev/gemini-api/docs/models
- Google, Gemini 3.8 Flash spec sheet: "1,048,576" input, "65,536" output; "Structured outputs: Supported"; "our most intelligent Flash model, engineered for long-horizon software engineering, autonomous agents". https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash
- Google, pricing (2026-09-11): "$0.75 through December 31, 2026. $1.50 starting January 1, 2027". https://ai.google.dev/gemini-api/docs/pricing
- Gemini CLI, subagents: fields `name, description, model, tools, mcpServers, max_turns, timeout_mins, temperature`; "independent context window". https://geminicli.com/docs/core/subagents/
- OpenAI, GPT-5.6 Luna (read 15-sep-2026): "1,050,000 context window", "128,000 max output tokens", "Reasoning.effort supports: none, low, medium (default), high, xhigh, and max". https://developers.openai.com/api/docs/models/gpt-5.6-luna
- GPT-5.6 pricing (15-sep-2026): Sol $5/$30, Terra $2/$12, Luna $0.20/$1.20; "generic `gpt-5.6` alias routes to `gpt-5.6-sol`". https://www.cometapi.com/gpt-5-6-pricing/
- Harnesses measured 15-sep-2026: `codex exec -m gpt-5.6-luna` answered in 4,398 tokens; `gemini -p … --skip-trust` needs directory trust headless. https://geminicli.com/docs/cli/trusted-folders/
- Codex CLI, custom agents in TOML with `model`/`mcp_servers` per agent. https://simonwillison.net/2026/Mar/16/codex-subagents/
- Anthropic, model/pricing table (`claude-api` skill, cached 2026-06-24): Fable 5.1 $10/$50, Opus 5 $5/$25, Sonnet 5 $2/$10, Haiku 4.5 $1/$5.
