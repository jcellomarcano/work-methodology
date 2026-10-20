# Using the kit with other harnesses and local models

The kit installs itself for Claude Code and pi (`03-tools/bin/init.sh`). This page says what works on Codex
CLI, Google Antigravity and OpenCode by hand, with no installer (owner decision L2, `odd/tasks/harness-guides.md`),
and how to run local models. Read the matrix, then the section for your harness and what it leaves unenforced.

Tags: **[Measured]** seen in a local `--help` or command on 2026-10-18 (codex-cli 0.154.0, agy 1.3.5, opencode
1.18.25, pi 1.3.0); **[Documented]** an official page says so (id in the dossier); **[Unverified]** never run
end to end here, or inferred. `<kit>` = this checkout, `<tools>` = the tools instance, `<repo>` = the target.

## Support matrix

✅ the kit installer sets it up · 🟡 manual steps on this page · ❌ not available (or unsafe as is).
Sources: RA = `00-principles/runtime-adapters.md`; CX, AG, OC = the Codex, Antigravity, OpenCode dossiers;
LO = `odd/research/model-router/local.md`; RM = `odd/research/model-router/routing-method.md`.

| Kit element | Claude Code | pi | Codex CLI | Antigravity (App / CLI `agy`) | OpenCode |
|---|---|---|---|---|---|
| Instruction file | 🟡 the repo's `CLAUDE.md`; the kit writes none | 🟡 the repo's `AGENTS.md` or `CLAUDE.md` | 🟡 `AGENTS.md`, read automatically (CX §1) | 🟡 `AGENTS.md` or `GEMINI.md` (AG §2) | 🟡 `AGENTS.md` plus `instructions` (OC §1) |
| Skills | ✅ `.claude/skills/` (RA §2) | ✅ `.pi/skills/` (RA §2) | 🟡 `.agents/skills` (CX §1, §2.3) | 🟡 `.agents/skills/` (AG §2) | 🟡 reads `.claude/skills/` (OC §1) |
| `metodo` MCP server | ✅ `.mcp.json` (RA §2) | ✅ `.mcp.json` + `.pi/mcp.json` (RA §2) | 🟡 `.codex/config.toml` (CX §2.1) | 🟡 `.agents/mcp_config.json` (AG §3) | 🟡 `opencode.json`; tools named `metodo_<tool>` (OC §2.1) |
| Role agents with model + effort | ✅ `.claude/agents/`, model pinned (RA §2) | ✅ `.pi/agents/`; model and effort per launch (RA §2, RM §6) | 🟡 `.codex/agents/*.toml` (CX §2.3) | 🟡 `.agents/agents/`; model tier only, effort per process (AG §2) | 🟡 `.opencode/agents/*.md`, `model` + `variant` (OC §2.3) |
| Router roster at launch | ✅ `mcp__metodo__route` (RM §6) | ✅ same tool; `pi --model` (RM §6) | 🟡 one `codex exec` per role (CX §2.4) | 🟡 one `agy -p` per role (AG §3) | 🟡 `opencode run` per role (OC §2.6) |
| Guard hooks | ✅ seven hooks (RA §2) | ✅ `.pi/extensions/metodo-hooks.ts` (RA §2) | 🟡 gates and Bash log; path guard ❌ (CX §2.5) | ❌ payload differs (AG §3, §5) | 🟡 `permission.edit` denies; Python guards ❌ (OC §2.4, §2.5) |
| Per-subagent budget | ✅ `budget.py` (RA §2) | ✅ one counter per subagent (RA §2) | ❌ no per-agent cap known (CX §1) | ❌ no role in the payload (AG §2) | 🟡 `steps` caps turns, not tool calls (OC §1) |
| Output check on close | ✅ blocks once (RA §2) | ✅ recorded, cannot block (RA §2) | 🟡 `SubagentStop` entry, unverified (CX §2.5) | ❌ no SubagentStop (AG §2) | ❌ no blocking check (OC §1) |
| Local models | ❌ unsupported by Anthropic; avoid (LO §3, §4) | 🟡 `models.json` provider (LO §3) | 🟡 `--oss` (CX §3) | ❌ App/CLI; Python SDK only (AG §4) | 🟡 custom provider (OC §3) |

Checkers, receipts and memory run in the kit's scripts and MCP server, so every 🟡 harness keeps them (OC §1).
Add every path you create to `<repo>/.git/info/exclude`, as the installers do (RA §3).

## Codex CLI

1. **Trust the project**: untrusted projects skip `.codex/` config, hooks and rules; trusting is an owner
   step (onboarding prompt or `/permissions`) [Documented, CX §2].
2. **Register `metodo`** in `<repo>/.codex/config.toml`, absolute paths (TOML expansion is undocumented)
   [Documented, CX §2.1]:
   ```toml
   [mcp_servers.metodo]
   command = "python3"
   args = ["<tools>/mcp/server.py"]
   startup_timeout_sec = 20
   [mcp_servers.metodo.env]
   METODO_TOOLS = "<tools>"
   METODO_REPO = "<repo>"
   ```
   Skip `codex mcp add`: it likely writes the user-level file, pinning one repo for all [Unverified]. Check
   with `codex mcp list` [Measured: subcommand exists].
3. **Instruction file**: the target's `AGENTS.md` loads by itself, up to 32 KiB [Documented]. Add one line
   (`Methodology: read <kit>/CONTEXT-PACK.md first.`), never a copy; avoid `model_instructions_file`, which
   replaces `AGENTS.md` [Documented, CX §2.2].
4. **One role as an agent**, `<repo>/.codex/agents/generic-verifier.toml` [Documented fields, CX §2.3]:
   ```toml
   name = "generic-verifier"
   description = "Independent, clean-context executor - runs the battery a change card names and reports a verdict."
   model = "gpt-6.1-sol"
   model_reasoning_effort = "medium"
   developer_instructions = """
   <python3 <kit>/03-tools/lib/render_agents.py --target pi <kit>/01-roles/agents/generic-verifier.md, frontmatter cut>
   """
   ```
   Model and effort: `03-tools/config/model-tiers.json`, OpenAI medium tier, `candidate`. Local 0.154.0 lacks
   `gpt-6.1-sol` (`gpt-5.6-terra` meanwhile) and a hyphen in `name` is undocumented [Unverified].
5. **Skills**: `03-tools/bin/install.sh <repo> --runtime claude`, then `ln -s ../.claude/skills
   <repo>/.agents/skills`; Codex follows symlinked skill folders [Documented; this combination Unverified].
6. **Apply the router's roster**: `03-tools/bin/route.sh <task.json> --as-of <date>` prints `role`,
   `provider`, `model`, `effort` per entry; launch one process per role [Measured flags; never run here]:
   ```bash
   codex exec -m "$model" -c model_reasoning_effort="$effort" --sandbox read-only \
     --output-schema <tools>/schemas/verification.schema.json -o out/<round>/<n>-verifier.json "<brief>"
   ```
   `codex exec` 0.154.0 has no `-a` flag, so the dossier's `-a never` is left out [Measured]. Writers use
   `--sandbox workspace-write`. An agent file's `model` and effort beat the spawn request: omit them to let
   the router escalate [Documented, CX §2.4]. The kit's schemas as `--output-schema`: [Unverified].
7. **Guards**: `sed "s|__TOOLS_DEFAULT__|<tools>|g" <kit>/03-tools/hooks/hooks.settings.json >
   <repo>/.codex/hooks.json`, add a `SubagentStop` entry running `validate_subagent_output.py`, trust them in
   `/hooks` [Documented shape; Unverified file]. Add `.codex/rules/metodo.rules` with `prefix_rule(pattern =
   ["git", "push"], decision = "forbidden")` and the same for `["gh", "pr"]` [Documented, CX §2.5].

**What is NOT enforced on Codex.**
- The path guard lets every edit through: `guard_paths.py` reads `tool_input.file_path`
  (`03-tools/hooks/guard_paths.py:19`), Codex edits arrive as `apply_patch` with `tool_input.command`, and
  the script exits 0 when the path is missing. Shared build files and `may_write` scope are unguarded.
- An owner `ask` fails open: Codex parses `permissionDecision: "ask"`, marks the hook failed and runs the
  tool [Documented].
- The budget: no per-agent cap key; `budget.py` needs `agent_type` in PreToolUse [Unverified on 0.154.0].
- Per-role tools, sandbox and MCP: subagents inherit the parent's; a contract's tool list is prose only.
- Hook trust is per hash: untrusted hooks are skipped, so a headless `codex exec` may run unguarded after a kit
  update [Unverified]. `--dangerously-bypass-hook-trust` exists [Measured]; that is the owner's call.

## Google Antigravity (App and CLI `agy`)

App and `agy` share one harness and settings; the IDE has no custom subagents; Gemini 4 Argon needs a paid
plan and is absent from the IDE (AG §1). Every step below is [Unverified] end to end.

1. **Instruction file**: `AGENTS.md` (or `GEMINI.md`) at the root, at most 24,000 bytes, no frontmatter
   [Documented, A5]. Plain `@file` does not inline; `@[identity](<path>)` does [Documented; Unverified here].
2. **Register `metodo`** in `<repo>/.agents/mcp_config.json`, literal absolute paths, no `"type"` key
   [Documented, A4]:
   ```json
   {"mcpServers": {"metodo": {"command": "python3", "args": ["<tools>/mcp/server.py"],
     "env": {"METODO_TOOLS": "<tools>", "METODO_REPO": "<repo>"}, "cwd": "<repo>"}}}
   ```
   Check with `/mcp`. MCP tools default to Ask, soft-denied under `agy -p`; allowing `"mcp(metodo/*)"` is a global
   setting, the owner's decision [Documented, A4, A11, A13]. `agy mcp add` has no scope flag [Measured].
3. **Skills**: copy each kit skill folder to `<repo>/.agents/skills/<name>/` [Documented, A6].
4. **One role as an agent**, `<repo>/.agents/agents/generic-verifier/agent.md`: the `render_agents.py
   --target pi` body under this frontmatter [Documented keys, A8, A9]:
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
   `model` is a tier (`inherit`, `flash`, `pro`), not an id. No `invoke_subagent`, to keep the no-spawn rule;
   a misspelled tool name may hang the subagent [Documented, A8].
5. **Apply the router's roster**: per `launch: "run"` entry with `provider: "google"`, one process
   [Measured flags: `-p`, `--agent`, `--model`, `--output-format`, `--effort`]:
   ```bash
   agy -p "<brief>" --agent generic-verifier --model gemini-3.8-flash-medium --output-format json
   ```
   The id-plus-effort slug follows A11's list [Unverified pattern]; an unknown `--model` fails, never falls
   back [Documented]. The small tier has no equivalent (no Flash-Lite, no effort below `low`). Check outputs
   on the orchestrator side with `lib/round_output.py` and `lib/cite_check.py`.

**What is NOT enforced on Antigravity.**
- No kit guard. Do not wire `03-tools/hooks/*.py` into `.agents/hooks.json` as they are: the payload is
  camelCase with other tool names (`write_to_file`, `run_command`), the scripts read `tool_input.file_path`
  and fail open on unexpected input (`_common.py:4`), so they would silently allow everything (AG §3, §5).
- No budget (no role in the payload), no output check (no SubagentStop event) (AG §2).
- Nesting up to 10 levels against the kit's depth 1; only the `tools` allowlist stops a role from spawning.
- Effort per role is session-wide. App/CLI MCP tool names are undocumented (the SDK uses
  `mcp_{server_name}_{tool_name}`), so no receipt-gate matcher can be written [Unknown] (AG §5).

## OpenCode (V1)

1. **Register `metodo`** in `<repo>/opencode.json` [Documented, O5]:
   ```json
   { "$schema": "https://opencode.ai/config.json",
     "mcp": { "metodo": { "type": "local", "enabled": true, "timeout": 10000,
       "command": ["python3", "<tools>/mcp/server.py"], "environment": { "METODO_TOOLS": "<tools>" } } } }
   ```
   Absolute paths: an unset `{env:VAR}` becomes empty [Documented]. No `METODO_REPO`: the server starts in the
   project and falls back to `git rev-parse` [Unverified]. Check with `opencode mcp list` [Measured].
2. **Instruction file**: OpenCode reads `AGENTS.md`, else `CLAUDE.md`; add `"instructions":
   ["<kit>/CONTEXT-PACK.md"]` [Documented, O4]. Skills in `.claude/skills/` load as is [Documented, O9].
3. **One role as a subagent**, `<repo>/.opencode/agents/generic-verifier.md` (file name = agent name
   [Documented, O2]); the `render_agents.py --target pi` body under this frontmatter [Unverified]:
   ```yaml
   ---
   description: Independent, clean-context executor - runs the battery a change card names and reports a verdict.
   mode: subagent
   model: anthropic/claude-sonnet-5-5
   variant: high
   temperature: 0
   steps: 50
   permission: { "*": deny, read: allow, grep: allow, glob: allow, list: allow, bash: allow, edit: deny,
     "metodo_*": deny, metodo_test_sectors: allow, metodo_verify_sectors: allow, metodo_verify_commit: allow,
     metodo_job_status: allow, metodo_receipt_status: allow, metodo_receipt_capture: allow,
     metodo_output_write: allow, metodo_handoff_write: allow }
   ---
   ```
   Check the model is listed with `opencode models anthropic`; use an API key (Anthropic prohibits
   subscription plugins) [Documented, O8]. The last matching permission rule wins [Documented, O3].
4. **Deny shared build files and `.claude/**`** in the role and the top-level `permission`; `*` matches any
   character, so `**/*.gradle` misses a root `build.gradle` [Documented, O3; Unverified run]:
   ```yaml
   edit: { "*": allow, "*.gradle": deny, "*.gradle.kts": deny, "*gradle.properties": deny,
     "*gradle/wrapper/*": deny, "*buildSrc/*": deny, "*build-logic/*": deny, ".claude/*": deny, "*/.claude/*": deny }
   ```
5. **Apply the router's roster**: `model: <provider>/<model>` and `variant: <effort>` in the role file, or
   [Measured flags: `--agent`, `--model`, `--variant`]:
   `opencode run --agent generic-verifier --model anthropic/claude-sonnet-5-5 --variant high "<task>"`.
   Pin every role: subagents otherwise take the primary agent's model [Documented, O2].

**What is NOT enforced on OpenCode.**
- The kit's Python guards: they need a TypeScript plugin in `.opencode/plugins/`, not written yet (sketch
  in OC §2.5); `--pure` turns plugins off.
- Bash edits (`sed -i build.gradle`) pass the `edit` permission; `gpt-` models edit through `apply_patch`
  with `patchText`, which a path guard would not see (OC §2.4, §2.5).
- MCP tool names differ: `metodo_<tool>`, not the `mcp__metodo__<tool>` roles and skills name (OC §2.1).
- No blocking output check; `steps` is not `max_tool_calls`; `@` calls any subagent despite task permissions
  [Documented, O2]. All of this is V1: V2 renames permissions and does not run V1 plugins [Documented, O13].

## Local models

**This machine** [Measured, LO §2]: Apple M1 Max, 64 GiB unified memory; Ollama client 0.34.4 (no server,
no model pulled), LM Studio `lms`, no `llama-server`. Working rule: weights at most ~40 GB, the rest for KV
cache and the OS [Unverified]. Tokens per second and tool-call reliability are [Unknown]: nothing was run.

| Size class (LO §2) | Q4 (`q4_K_M`) | Q8 (`q8_0`) | BF16 |
|---|---|---|---|
| up to 12B: Qwen3.5-9B (6.6 GB), Gemma 4 12B (8.0 GB) / E4B (6.6 GB) | fits, several at once | fits | fits |
| 24B-36B: Qwen3.8-27B, Qwen3.6-35B-A3B, Gemma 4 26B/31B, Devstral Small 2, GLM-4.7-Flash; `gpt-oss:20b` native MXFP4 14 GB | fits (15-25 GB), 64K-128K context | fits, reduced context | does not fit |
| 117B and up: `gpt-oss:120b` (65 GB), Qwen3.5-122B, Kimi K3 | does not fit | no | no |

Catalog local candidates, small tier only: `qwen3.5:9b-q4_K_M`, `gemma4:12b-it-q4_K_M`, `gpt-oss:20b`, effort
`off`/`on` (`03-tools/config/model-tiers.json`). Agents need 64K+ context; set it, Ollama's default varies (LO §3).

**Serve them** [`ollama`, `lms` subcommands Measured; `llama-server` not installed here; flags Documented, LO §3]:
- Ollama: `ollama pull <tag>`, `OLLAMA_CONTEXT_LENGTH=64000 ollama serve`; endpoint `http://localhost:11434/v1/`.
  Set `OLLAMA_NO_CLOUD=1`: `:cloud` tags run remotely.
- LM Studio: `lms load <model_key> --context-length <n>` (`--estimate-only` previews memory), then
  `lms server start --port 1234`; endpoint `http://localhost:1234/v1`.
- llama.cpp: `llama-server -m <file.gguf> -c <n> --jinja --reasoning-effort LEVEL`, `http://127.0.0.1:8080/v1`.

**Point each harness at them:**
- pi: provider `ollama` in `~/.pi/agent/models.json` (`"baseUrl": "http://localhost:11434/v1"`, `"api": "openai-completions"`,
  `"apiKey": "ollama"`, `"models": [{ "id": "<tag>" }]`), then `pi --model ollama/<tag>:<thinking>` [Documented, LO §3].
- Codex CLI: `codex exec --oss --local-provider ollama -m <tag> "<brief>"` (or `lmstudio`) [Measured flags];
  other endpoints go in user-level `[model_providers.<id>]` and must speak `/v1/responses` [Documented, CX §3].
- OpenCode: a provider with `"npm": "@ai-sdk/openai-compatible"`, `"options": {"baseURL":
  "http://localhost:11434/v1"}` and one `models` entry per tag with `limit.context` [Documented, OC §3].
- Antigravity: not in the App or `agy`; only the Python SDK's `LocalOpenAIAgentConfig` (AG §4).
- Claude Code: Ollama documents `ANTHROPIC_BASE_URL`, Anthropic does not support it: never for kit roles.

**Kit rule** (owner decision L4, `odd/tasks/model-router.md`): local models run only small-tier roles, only for
offline or privacy repos (`offline: true` in the task or `config/project.json`, or `METODO_OFFLINE=1`). Each
local entry stays `candidate` until a real run here passes the admission test of
`00-principles/multi-provider-routing.md` §4; how `off`/`on` maps onto Codex or OpenCode effort is [Unknown].

## Known gaps

- Nothing here ran end to end on Codex, Antigravity or OpenCode; each section is a manual recipe.
- Guards: Codex needs `guard_paths.py` to parse `apply_patch`; Antigravity a payload adapter; OpenCode the
  plugin sketched in OC §2.5. All new code, outside L2.
- The default roster picks only admitted Anthropic models; OpenAI, Google and local entries are `candidate`
  and need the owner's OK (CX §2.4, AG §3).
- `model-tiers.json` `harness.codex-cli` lists `sandbox` and `mcp_servers` as agent fields, which the Codex
  docs contradict, and there is no `opencode` or `antigravity` entry (CX §4, OC §2.6). Not fixed here.

Dossiers: [Codex CLI](../odd/research/harnesses/codex.md) · [Antigravity](../odd/research/harnesses/antigravity.md) ·
[OpenCode](../odd/research/harnesses/opencode.md) · [local models](../odd/research/model-router/local.md) ·
[routing §6](../odd/research/model-router/routing-method.md) · [runtime adapters](../00-principles/runtime-adapters.md).
