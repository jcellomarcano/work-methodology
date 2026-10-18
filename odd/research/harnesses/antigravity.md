# Research H2: Google Antigravity (read 2026-10-18)

Specs S1, S3 of `odd/tasks/harness-guides.md`. Curly-quoted text is verbatim from the cited source (checked
by script, §6). Tags: [Measured] = local read-only command on 2026-10-18; [Inferred] = conclusion from cited
text; [Unverified] = documented step never run here; [Unknown] = sources silent. Kit refs are `@44bd74c`.

## 1. What Antigravity is today

Antigravity is a family of surfaces, not one tool. [A1]: “Google Antigravity is an advanced agentic coding
platform and CLI designed for orchestrating autonomous subagents, scheduled tasks, and interactive code
verification.” App and CLI [A17]: “These products use the same Antigravity agent harness, share the same
settings”.

| Surface | What it is | Local state [Measured] |
|---|---|---|
| Antigravity App ("2.0") | Desktop agent manager. [A16]: “Users interact with powerful agents both synchronously and asynchronously, and there is no IDE.” | `/Applications/Antigravity.app`, bundle `com.google.antigravity` 2.23.1 |
| Antigravity CLI (`agy`) | Terminal client on the same harness, Go binary; [G1]: “Built in Go, Antigravity CLI is snappier and more responsive.” | `~/.local/bin/agy`, `agy --version` → `1.3.5`; `antigravity` not on PATH |
| Antigravity IDE | The Nov-2025 editor; MCP, rules, skills, hooks apply; custom subagents are documented for App and CLI only [A8] | `/Applications/Antigravity IDE.app`, `com.google.antigravity-ide` 2.5.5 |
| IDE extensions, SDK | Extensions for VS Code, JetBrains, Visual Studio, Zed, Xcode [A1]; Python SDK `google-antigravity` [A14] | not checked |
| Managed agent (Gemini API) | `antigravity-preview-09-2026`, a Google-hosted Linux sandbox that, per [G5], “uses the same harness as the Antigravity IDE”; [G2]: “Managed agents are in Public Preview.” | not applicable (remote) |

Gemini CLI status. [G1] (2026-05-19): “On June 18, 2026, Gemini CLI and Gemini Code Assist IDE extensions will
stop serving requests for Google AI Pro and Ultra, as well as those using it free of charge using Gemini Code
Assist for individuals.” Banner on geminicli.com [C2]: “Gemini CLI was replaced by Antigravity CLI on June
18th, 2026.” It survives for paid keys [G1]: “Gemini CLI will remain accessible via paid Gemini and Gemini
Enterprise Agent Platform API keys.” Argon [C1, C2]: “Gemini CLI has not been optimized for Gemini 4 Argon.”
Local `gemini --version` → `0.63.0` [Measured].

Argon in Antigravity [A18]: “available in the Antigravity desktop app and the Antigravity CLI”; the models
page adds [A3]: “Not available in Antigravity IDE.” Plan table [A3]: Argon needs a paid (non-trial) Google AI
Pro, Ultra or Enterprise plan; Free and Google AI Plus have Gemini 3.8 Flash but not Argon.

## 2. Kit needs → Antigravity equivalents

App and CLI share one harness [A17]; IDE differs where noted. "Managed" = the Gemini API managed agent.

| Kit need | App + CLI (`agy`) | IDE | Managed agent | Source |
|---|---|---|---|---|
| Instruction file | Supported: `AGENTS.md` or `GEMINI.md` per directory, plus `.agents/rules/*.md` with `trigger:` frontmatter | Supported, same files | Partial: `.agents/AGENTS.md` mounted into the sandbox | A5, A12, G3 |
| Per-role agent definition | Supported: `.agents/agents/<name>.md` or `.agents/agents/<name>/agent.md`, YAML `name`, `description`, `tools`, `model`, `mainAgent`, `subagent`, `mcpServers`, `skills` | Not documented (subagents page lists App and CLI only) | Partial: one `system_instruction` per named agent | A8, A9, G3 |
| Per-role exact model | Partial: subagent `model` is a tier, “Model tier used when invoked (inherit, flash, or pro).”; exact slug only per session (`--model`) | per session picker | Partial: `agent_config.model` | A8, A11, G3 |
| Per-role effort / thinking | Partial: no frontmatter key; per session `--effort` or effort-suffixed slug; levels low…max depend on model | picker: “choose a thinking level (Low, Medium, or High)” | Not documented | A3, A10, A11 |
| Skills (`02-skills/`) | Supported: `.agents/skills/<name>/SKILL.md` | Supported | Partial: mounted `.agents/skills/` | A6, G3 |
| `metodo` MCP (stdio) | Supported: `.agents/mcp_config.json`, `mcpServers` with `command`, `args`, `env`, `cwd` | Supported, same file | Not supported for stdio: it can “register remote MCP servers” | A4, G3 |
| Tool names `mcp__metodo__*` in role bodies | Unknown: App/CLI naming of MCP tools is not documented; the SDK uses `mcp_{server_name}_{tool_name}` | Unknown | Unknown | A15 |
| Guards (`guard_paths`, `guard_gates`) | Partial: `.agents/hooks.json` has `PreToolUse` with `decision: "deny"`, but the payload differs from Claude Code's (see §5) | Supported, same file | Partial: sandbox-side hooks | A7, G6 |
| Budget per subagent (`budget.py`) | Not supported as is: hook payload carries `conversationId`, no agent role | same | Not documented | A7, G6 |
| Output check on close | Not supported: no SubagentStop event; `Stop` can force continue | same | Not documented | A7, G6 |
| Session status, reply lint | Partial: `SessionStart` and `Stop` exist, JSON contract differs | same | Not documented | A7, G6 |
| Isolated context per agent | Supported: subagent “does not inherit the parent’s existing conversation history” | Not documented | Not supported: “No subagent nesting” | A8, G3 |
| `may_spawn: []` / depth 1 | Partial: nesting is allowed up to “A maximum nesting depth of 10 levels”; restrict `tools` to keep a role from spawning | — | n/a | A8 |
| Headless / scripting | Supported: `agy -p`, `--output-format json`, `--json-schema`, `--agent`, `--model`, `--effort` | Not documented | Supported (Interactions API) | A11 |
| Local models | Not documented (see §4) | Not documented | Not supported | A14, A15 |

## 3. Using the kit with Antigravity today (no installer)

`<repo>` = target repo, `<kit>` = this kit's checkout, `<tools>` = absolute path of the synced tools
instance. Every step writes inside `<repo>`; add each new path to `<repo>/.git/info/exclude`, as the kit's
installers do. None of these steps was run end to end [Unverified].

1. **Instruction file.** Keep `AGENTS.md` at the repo root (always on; [A5] “AGENTS.md and GEMINI.md do not use
   frontmatter.”); limits 24,000 bytes per file, 20,000 tokens for all always-on rules [A5]. The kit adapter
   `07-communication/adapters/GEMINI.md` uses `@../identidad.es.md`, but in Antigravity “@filename: Does not
   inline file contents.”; write `@[identity](../identidad.es.md)`, which inlines [A5] [Inferred].
2. **Register `metodo`.** Write `<repo>/.agents/mcp_config.json` [A4]:
   ```json
   {"mcpServers": {"metodo": {"command": "python3", "args": ["<tools>/mcp/server.py"],
     "env": {"METODO_TOOLS": "<tools>", "METODO_REPO": "<repo>"}, "cwd": "<repo>"}}}
   ```
   Differences from `lib/mcp_config.py`: no `"type": "stdio"` (not in [A4]'s property list) and literal
   absolute paths, because env-var expansion in `mcp_config.json` is not documented [Unknown]. Check with
   `/mcp`. `agy mcp add --help` shows `--env`, `--type` and no scope flag [Measured], so the file it writes is
   [Unknown]; edit the workspace file by hand.
   Approval: [A4] “By default, unconfigured MCP tools run in Ask mode, requiring your approval before
   execution.” In `agy -p` an unapproved tool is soft-denied [A11]. Granting `"mcp(metodo/*)"` under
   `permissions.allow` lives in the global `~/.gemini/antigravity-cli/settings.json` [A11, A13]: the owner's
   decision, never the kit's.
3. **Skills.** Copy each kit skill folder to `<repo>/.agents/skills/<name>/` [A6]. Whether Antigravity
   honours `allowed-tools` is [Unknown].
4. **One role as an agent.** `python3 <kit>/03-tools/lib/render_agents.py --target pi
   <kit>/01-roles/agents/generic-verifier.md` prints the body plus the contract as prose (no hook enforces it
   here). Swap its frontmatter for this one and save it as `<repo>/.agents/agents/generic-verifier/agent.md` [A9]:
   ```yaml
   ---
   name: generic-verifier
   description: Independent, clean-context executor - runs the battery a change card names and reports a verdict.
   tools: [view_file, grep_search, find_by_name, list_dir, run_command]
   model: flash
   mainAgent: true
   subagent: true
   commandExecutionPolicy: sandbox
   ---
   ```
   Tool names are from [A7]'s tool list; [A8]: “Specifying an unmapped or misspelled tool name in the tools
   list may cause the subagent process to hang during execution.” No `invoke_subagent`, to keep `may_spawn: []`.
   Exposing `metodo` to the agent is [Unknown]: [A8] lists an `mcpServers` key without its object shape;
   the changelog adds an `inheritCustomizations` switch [A15]. `model-tiers.json` (Google, `candidate`):
   verifier → `gemini-3.8-flash` at `medium`; a subagent only gets the `flash` tier, so pin both per process:
   `agy -p "<brief>" --agent generic-verifier --model gemini-3.8-flash-medium --output-format json`.
   Slugs listed in [A11] include `gemini-4-argon-high`, `gemini-4-argon-medium`, `gemini-3.8-flash-high`,
   `gemini-3.8-flash-medium`; [A11]: “headless mode doesn’t silently fall back when --model names an unknown
   model.” Large tier (challenger, blind-spot adversary, P0 judge) → `gemini-4-argon-high`. Small tier
   (`gemini-3.5-flash-lite`, `minimal`) has no Antigravity equivalent: Flash-Lite is not on the model list
   [A3], and `--effort` has no level below `low` [A10].
5. **Apply the router's roster.** `<tools>/bin/route.sh <task.json> --as-of <date>` prints rows with
   `role`, `provider`, `model`, `effort`, `launch`, `order`, `step` (`03-tools/lib/router.py:450-462`). For each
   `launch: "run"` row with `provider: "google"`, start one `agy -p … --agent <role> --model <model>-<effort>`
   (id + effort is the slug pattern of [A11]'s list [Inferred]), honouring `order`/`step`. The default roster
   picks only Anthropic models (`router.py:331`); Antigravity lists Claude Sonnet 5.5 and Opus 5.5
   (Thinking) on paid plans [A3], but their slugs and effort control are [Unknown]. Check each output on the
   orchestrator side with `lib/round_output.py` and `lib/cite_check.py` (`multi-provider-routing.md` §3).
6. **Guards.** Do not wire `03-tools/hooks/*.py` into `.agents/hooks.json` as they are: they read Claude
   Code's `tool_input.file_path` (`guard_paths.py:19`) and fail open on unexpected input (`_common.py:4`),
   so they would silently allow everything [Inferred]. An adapter is future work (§5).

**Gemini CLI path (paid API key or Enterprise only [G1]).** Agents `.gemini/agents/<role>.md` with an exact
`model` id, `max_turns`, `timeout_mins` [C2]; effort via `modelConfigs.overrides` [Inferred, `google.md` §3];
MCP `mcpServers` in `.gemini/settings.json` with `${VAR}` expansion in `env` [C3]; hooks `BeforeTool`/`AfterTool`
there too [C4]; headless `gemini -p … -m <id> --skip-trust` (`multi-provider-routing.md` §5). Unlike the
Antigravity App and CLI, it can run the small tier (`gemini-3.5-flash-lite`).

## 4. Local models

- App, CLI, IDE: no documentation page describes local models [Unknown]. The CLI changelog mentions
  “custom models configured in settings.json” (v1.2.8, 2026-09-22) and a `GOOGLE_GEMINI_BASE_URL` for custom
  endpoints with `modelProvider: "gemini"` (v1.1.13, 2026-08-14) [A15], but the settings schema is not
  documented. Treat local models in `agy` as not supported until documented and measured.
- SDK: supported. [A14]: “LocalOpenAIAgentConfig: Connects to an external local server with an
  OpenAI-compatible API, such as Ollama, LM Studio, or vLLM.” Also `LiteRTAgentConfig` for on-device
  `.litertlm` checkpoints (Gemma 4 26B A4B). The SDK changelog says MCP and subagents work with both [A15].
  The SDK is Python code, not a harness the kit can install into; using it means writing a runner [Inferred].
- Managed agent: not supported; Google-hosted sandbox, Gemini models only [G3]. "GPT-OSS 120B" in the
  App/CLI picker is hosted, not local, and leaves on 2026-11-02 [A3].

## 5. Gaps and risks

- **Effort per role is session-wide.** No agent frontmatter key sets thinking; subagents get only
  `inherit|flash|pro` [A8]. Exact model + effort per role requires one `agy -p` process per role.
- **Hook contract differs.** [A7]: “Hooks receive input through stdin as JSON and return output through
  stdout as JSON. Field names use camelCase.” Tool names differ (`write_to_file`, `replace_file_content`,
  `run_command`), the payload names no role [Inferred from its common fields], and there is no SubagentStop.
  Budget and output checks need an adapter script; until then the contract is prose only, as on pi.
- **MCP tool names.** Role bodies and the receipt-gate matcher (`hooks.settings.json`) use `mcp__metodo__*`; App/CLI naming
  is undocumented, so a receipt-gate matcher cannot be written yet [Unknown].
- **Approvals and plans.** MCP tools default to Ask and are soft-denied headless; permissions are global
  files. Argon needs a paid plan and is absent from the IDE [A3]. Free use of `agy` exists but quotas apply.
- **Nesting.** Antigravity allows 10 levels [A8] against the kit's depth 1; only the `tools` allowlist
  prevents spawning, and a typo there can hang the agent [A8].
- **Managed agent docs disagree.** [G3] still says “Supported model options in agent_config are
  gemini-3.8-flash (default), gemini-3.6-flash, and gemini-3.5-flash-lite.” while [G4] says “The
  Antigravity agent in Gemini Managed Agents supports Gemini 4 Argon.” Same conflict as `google.md` §3.
- **Volatility.** CLI releases land every few days: v1.3.0 on 2026-10-06 to v1.4.0 on 2026-10-16 [A15];
  local `agy` is 1.3.5. Re-read the docs before writing an `install-antigravity.sh`.

## 6. Sources (all read 2026-10-18 with `curl -sL --compressed`; HTTP status as fetched)

| id | URL | HTTP | id | URL | HTTP |
|---|---|---|---|---|---|
| A1 | https://antigravity.google/llms.txt | 200 | A2 | https://antigravity.google/docs/overview/ | 200 |
| A3 | https://antigravity.google/docs/models/ | 200 | A4 | https://antigravity.google/docs/mcp/ | 200 |
| A5 | https://antigravity.google/docs/rules/ | 200 | A6 | https://antigravity.google/docs/skills/ | 200 |
| A7 | https://antigravity.google/docs/hooks/ | 200 | A8 | https://antigravity.google/docs/subagents/ | 200 |
| A9 | https://antigravity.google/docs/cli/commands/agents/ | 200 | A10 | https://antigravity.google/docs/cli/commands/effort/ | 200 |
| A11 | https://antigravity.google/docs/cli/headless/ | 200 | A12 | https://antigravity.google/docs/cli/gcli-migration/ | 200 |
| A13 | https://antigravity.google/docs/permissions/ | 200 | A14 | https://antigravity.google/docs/sdk/local-models/ | 200 |
| A15 | https://antigravity.google/docs/changelog/ | 200 | A16 | https://antigravity.google/blog/introducing-google-antigravity-2/ (2026-05-19) | 200 |
| A17 | https://antigravity.google/blog/introducing-google-antigravity-cli/ (2026-05-19) | 200 | A18 | https://antigravity.google/blog/gemini-4-argon-in-google-antigravity/ (2026-10-13) | 200 |
| G1 | https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli (2026-05-19) | 200 | G2 | https://ai.google.dev/gemini-api/docs/agents | 200 |
| G3 | https://ai.google.dev/gemini-api/docs/custom-agents | 200 | G4 | https://ai.google.dev/gemini-api/docs/latest-model | 200 |
| G5 | https://ai.google.dev/gemini-api/docs/antigravity-agent | 200 | G6 | https://ai.google.dev/gemini-api/docs/agent-hooks | 200 |
| C1 | https://raw.githubusercontent.com/google-gemini/gemini-cli/main/README.md | 200 | C2 | https://geminicli.com/docs/core/subagents/ | 200 |
| C3 | https://geminicli.com/docs/tools/mcp-server/ | 200 | C4 | https://geminicli.com/docs/hooks/ | 200 |

Cross-checks only (200, antigravity.google): `/docs/{getting-started,settings,cli/reference}/`, `/docs/sdk/*`,
`/product/*`, `sitemap.xml`. Failed: https://ai.google.dev/gemini-api/docs/antigravity → 404 (guessed; G5 is
the page); `/docs/cli` → meta-refresh to `/docs/getting-started?tab=cli`. Local [Measured]: `which`, `--version`
and `--help` of `agy`/`gemini`, `agy help {mcp,agents,plugin,models}`, `agy mcp add --help`, app `Info.plist`.

Quote check (2026-10-18): a script took every curly-quoted span here and searched the fetched pages (HTML
tags stripped; whitespace, curly apostrophes and markdown `*`/`` ` `` normalized): 28/28 found, 0 missing.
