# Research H1: the kit on Codex CLI (read 2026-10-18)

Task H1 of `odd/tasks/harness-guides.md` (S1, S3). Tags: **[M]** measured (verbatim on a fetched page S#, or a local
command L1), **[I]** inferred, **[U]** unknown. Double-quoted prose is verbatim and quote-checked (§5). Kit citations
are `file:line@44bd74c` (committed HEAD). Nothing ran end to end in a live Codex session; `~/.codex` was not touched.

## 1. Kit needs mapped to Codex

| Kit need (kit source) | Codex equivalent | Status | Source |
|---|---|---|---|
| Instruction file (`AGENTS.md` of the target repo) | read automatically: "Codex reads `AGENTS.md` files before doing any work."; root to cwd, "Codex includes at most one file per directory.", cap "`project_doc_max_bytes` (32 KiB by default)" | supported | S2 [M] |
| The kit's own `AGENTS.md` / `CONTEXT-PACK.md` from a target repo | not discovered: only `$CODEX_HOME` and the project chain are read; point at them from the target `AGENTS.md` (§2.2) | partial | S2 [M], [I] |
| Roles as agents (`01-roles/agents/generic-*.md`) | `.codex/agents/<name>.toml`, required `name`, `description`, `developer_instructions`; optional `model`, `model_reasoning_effort` | supported | S3 [M] |
| Per-role tool list (`tools:` frontmatter, contract `tools`) | none per agent: "They inherit the parent's permissions, provider, and MCP servers; a custom agent file can't override those settings."; per agent only `features.shell_tool = false` (and apps, plugins, memories); session-wide `mcp_servers.metodo.enabled_tools` | partial | S3, S7 [M] |
| Per-role sandbox (read-only roles) | not per agent: "Custom agent instructions can ask an agent to avoid edits, but they don't create a separate read-only sandbox."; set `--sandbox read-only` on the parent | partial | S3 [M] |
| Call budget (`max_tool_calls`, `maxTurns`; `budget.py`) | no per-agent turn or call cap key; `budget.py` needs `agent_type`/`agent_id` in PreToolUse input: optional in the `main`-branch schema, absent from the release docs | unknown | S3, S6, S12 [M]; [U] for 0.154.0 |
| Skills (`02-skills/<name>/SKILL.md`) | "For repositories, Codex scans `.agents/skills` in every directory from your current working directory up to the repository root."; "The `SKILL.md` file must include `name` and `description`." | supported | S8 [M] |
| `metodo` MCP server (`.mcp.json`, `mcp_config.py`) | `[mcp_servers.metodo]` with `command`, `args`, `env`; "you can also scope MCP servers to a project with `.codex/config.toml` (trusted projects only)."; or `codex mcp add` | supported | S7 [M], L1 [M] |
| Tool names `mcp__metodo__*` (role bodies, hook matchers) | hook matchers use the same form ("Match the MCP tool name, such as `mcp__filesystem__read_file`."); the model-facing name is not stated | partial | S6 [M]; model-facing [U] |
| Guard hooks (`hooks.settings.json`: PreToolUse, PostToolUse, SessionStart, Stop) | same event names and the same `{"hooks": {Event: [{matcher, hooks: [{type, command, timeout}]}]}}` shape in `<repo>/.codex/hooks.json`; deny via `permissionDecision: "deny"` or exit 2; "Non-managed hooks must be reviewed and trusted before they run." | partial (§2.5) | S6 [M], L1 `hooks stable true` [M] |
| Path guard (`guard_paths.py`, `touched_paths.py`) | edits arrive as `apply_patch`: "`Bash` and `apply_patch` use `tool_input.command`."; the kit reads `tool_input.file_path` (`03-tools/hooks/guard_paths.py:19@44bd74c`) and exits 0 when it is missing | not enforced | S6 [M], [I] |
| Owner gate `ask` on a shared build file (`emit_pretool("ask")`) | `permissionDecision: "ask"` is "parsed but not supported yet"; "Codex marks the hook run as failed, reports the error, and continues the tool call." | not supported (fails open) | S6 [M] |
| Output check on close (`validate_subagent_output.py`, Stop hook in each role's frontmatter) | `SubagentStop` with `agent_type`, `stop_hook_active`, `decision: "block"`; must live in the global hooks file, agent TOML carries no hooks | partial | S6, S3 [M]; `agent_type` = TOML `name`? [U] |
| Receipt gate and Bash outcome log (`guard_gates.py`) | PreToolUse/PostToolUse match `Bash` and MCP names with the kit's field names (`tool_name`, `tool_input.command`) | partial | S6 [M]; works [I]; subagent deny needs `agent_type` [U] |
| Forbidden paths (`**/.claude/**`, shared build files) | `workspace-write` keeps `.git`, `.agents`, `.codex` read-only: "`<writable_root>/.git` is protected as read-only whether it appears as a directory or file."; shared build files are not covered | partial | S9 [M] |
| Delivery belongs to the owner (push, PR) | `.codex/rules/*.rules` `prefix_rule(..., decision = "forbidden")`: "`forbidden`: Block the request without prompting."; scope: "Use rules to control which commands Codex can run outside the sandbox." | partial | S10 [M] |
| Router model + effort per launch (`bin/route.sh`) | per process `codex exec -m <model> -c model_reasoning_effort=<effort>`; profile files; per agent file `model`/`model_reasoning_effort` | supported | L1 [M], S3, S4 [M] |
| Role output schema (`03-tools/schemas/*.schema.json`) | `codex exec --output-schema <FILE>`: "Path to a JSON Schema file describing the model's final response shape" | partial | L1 [M]; kit schemas accepted? [U] |
| Local models | `--oss`, `--local-provider`, `oss_provider = "ollama" # or "lmstudio"` | supported (§3) | L1, S4 [M] |

## 2. Using the kit with Codex today (no installer)

Prerequisite: a trusted project. "Untrusted projects skip project-scoped `.codex/` layers, including project-local
config, hooks, and rules." [S5 M]. Trusting is an owner step (onboarding prompt or `/permissions`). Add `.codex/` and
`.agents/` to `.git/info/exclude`, as the kit does for `.mcp.json` (`03-tools/bin/install-claude.sh:286-292@44bd74c`) [I].

### 2.1 Register the `metodo` MCP server

`<repo>/.codex/config.toml`, mirroring `render_entry` (`03-tools/lib/mcp_config.py:27-33@44bd74c`). Use absolute
paths: whether Codex expands `$HOME` or `${VAR:-default}` inside TOML is not stated [U].

```toml
[mcp_servers.metodo]
command = "python3"
args = ["<absolute-kit-path>/03-tools/mcp/server.py"]
startup_timeout_sec = 20   # default 10 (S7)
[mcp_servers.metodo.env]
METODO_TOOLS = "<absolute-kit-path>/03-tools"
METODO_REPO = "/abs/path/to/<repo>"
```

CLI form [M L1]: `codex mcp add metodo --env METODO_TOOLS=<tools> --env METODO_REPO=<repo> -- python3 <tools>/mcp/server.py`;
S7 keeps MCP config "By default" in `~/.codex/config.toml` [I: user level], pinning one `METODO_REPO` for every repo,
so prefer the project file. Check with `codex mcp list`; smoke first with `install-claude.sh:310@44bd74c`'s `--selftest`.

### 2.2 Point Codex at the instructions

- Target `AGENTS.md` loads by itself (S2; 32 KiB cap, `project_doc_max_bytes`). The kit's `AGENTS.md` (2,956 bytes) and
  `CONTEXT-PACK.md` (6,984 bytes) [M `wc -c`] load only inside the kit repo: add a pointer line to the target's file
  (`Methodology: read <kit>/CONTEXT-PACK.md first.`), never a copy (`runtime-adapters.md` §1). Outside-workspace reads: [U].
- Avoid `model_instructions_file`: it is a "Replacement for built-in instructions instead of `AGENTS.md`." [S5 M]

### 2.3 Express each role as a Codex custom agent

One TOML per role, `<repo>/.codex/agents/generic-verifier.toml` below. Model and effort: `model-tiers.json` medium tier,
`openai` `gpt-6.1-sol`, `effort_by_role.generic-verifier = "medium"`, status `candidate`. Body: the role file after its
frontmatter plus the contract prose `render_agents.py --target pi` renders (`render_agents.py:88-119@44bd74c`) [I]:

```toml
name = "generic-verifier"
description = "Independent, clean-context executor - runs the battery a change card names and reports a verdict from what it actually ran, never from what others claimed."
model = "gpt-6.1-sol"
model_reasoning_effort = "medium"
developer_instructions = """
<body of 01-roles/agents/generic-verifier.md after the closing --->
<the '## Contract' section from: python3 03-tools/lib/render_agents.py --target pi 01-roles/agents/generic-verifier.md>
"""
```

- "Codex identifies the custom agent by its `name` field." [S3 M]. Docs use underscores (`pr_explorer`); a hyphen is
  [U]. Keep `generic-verifier` if accepted: kit hooks find the contract by `agent_type` (`guard_paths.py:41@44bd74c`).
- Local 0.154.0 lacks `gpt-6.1-sol` (`odd/research/model-router/openai.md` §3); `gpt-5.6-terra` `medium` meanwhile [I].
- A no-shell role can set `[features]` `shell_tool = false` [S3 M]; it is not a read-only sandbox. Delegation is
  prompted: the orchestrator names the agent (openai.md §3).
- Skills [I, unverified]: render with the existing `03-tools/bin/install.sh <repo> --runtime claude`, then
  `ln -s ../.claude/skills <repo>/.agents/skills`; "Codex supports symlinked skill folders and follows the symlink target when scanning these locations." [S8 M]

### 2.4 Pass the router's roster to a launch

`03-tools/bin/route.sh <task.json> --as-of <date>` prints `role`, `provider`, `model`, `effort` per entry
(`03-tools/lib/router.py:451-455@44bd74c`). Three ways to honor it:

1. **One `codex exec` per role (recommended)** [M flags L1; never run here]: `codex exec -m "$model"
   -c model_reasoning_effort="$effort" --sandbox read-only -a never --output-schema
   03-tools/schemas/verification.schema.json -o out/<round>/<n>-verifier.json "<brief>"`. A bare `-c` value is fine:
   "If it fails to parse as TOML, the raw string is used as a literal." [L1 M]. `workspace-write` only for writers.
2. **Profiles**: `~/.codex/metodo-medium.config.toml`, run `codex exec -p metodo-medium`; "Use top-level config keys in
   the profile file; don't nest them under `[profiles.profile-name]`." [S4 M]
3. **Subagents**: "If a custom agent file sets `model` or `model_reasoning_effort`, the value in the file takes
   precedence." [S3 M]: to let the router escalate, omit both and state them in the spawn request [I].

Default rows pick only `admitted` entries, all Anthropic today (`router.py:331,336-338@44bd74c`), which Codex cannot
run; OpenAI and local entries are `candidate`, owner-gated (`router.py:341-347@44bd74c`) until the §4 test (`multi-provider-routing.md`) passes [I].

### 2.5 Guards: what holds and what does not

Render the hooks (`sed "s|__TOOLS_DEFAULT__|<tools>|g" <kit>/03-tools/hooks/hooks.settings.json > <repo>/.codex/hooks.json`),
add a `SubagentStop` entry running `validate_subagent_output.py` (agent TOML has no hooks), then trust them in `/hooks`.
The kit file's `_comment` key is outside Codex's documented shape (`description` is) [U: may warn or fail].

| Kit hook | On Codex | Tag |
|---|---|---|
| `guard_gates.py` Pre/Post `Bash`, receipt tools | same matcher and fields; denies with a shape Codex accepts | [I], unverified |
| `budget.py` (matcher `""`) | runs on every tool; counts only if PreToolUse carries `agent_type`/`agent_id` | [U] |
| `guard_paths.py`, `touched_paths.py` | fire on `apply_patch`, find no `file_path`, allow | not enforced [I] |
| `session_start_status.py`; `reply_lint.py` | "Plain text on `stdout` is added as extra developer context."; silent exit 0 accepted | [M S6]; [I] |
| `validate_subagent_output.py` | SubagentStop `decision: "block"` sends the subagent back | [I]; `agent_type` value [U] |

Closest safe substitute [M S9, S10; I]: read-only roles under `--sandbox read-only -a never`; writers under
`workspace-write` (`.git`, `.codex` stay read-only, network off by default); `.codex/rules/metodo.rules` with
`prefix_rule(pattern = ["git", "push"], decision = "forbidden")` and the same for `["gh", "pr"]`; never the two
`--dangerously-bypass-*` flags. Codex warns: "Treat tool hooks as a useful guardrail, not a complete enforcement
boundary." [S6 M]

## 3. Local models in Codex (only what the docs state)

- Flags [L1 M]: `--oss`; `--local-provider` "Specify which local provider to use (lmstudio or ollama)."; config
  `oss_provider = "ollama" # or "lmstudio"` [S4 M]. "If neither is set, the interactive CLI prompts you to choose;
  `codex exec` exits with an error." [S4 M]: headless kit runs must pass `--local-provider`.
- Ollama [S13 M]: "Use a context window of at least 64k tokens for Codex."; `ollama launch codex`, or `codex --oss -m
  gpt-oss:120b`, or profile `~/.codex/ollama-launch.config.toml` (`model_provider = "ollama-launch"`, provider table with
  `base_url = "http://localhost:11434/v1/"`, `wire_api = "responses"`) run as `codex --profile ollama-launch`.
- LM Studio [S14 M]: `lms server start --port 1234`, then `codex --oss`; "By default, Codex will download and use
  openai/gpt-oss-20b"; "Use a model (and server/model settings) with more than ~25k context length."
- Any OpenAI-compatible endpoint [S5 M]: `[model_providers.<id>]` `name`, `base_url`, `env_key`; on `wire_api`,
  "`responses` is the only supported value, and it is the default when omitted.", so the server must speak
  `/v1/responses` (Ollama and LM Studio do, `odd/research/model-router/local.md` §3). "Built-in provider IDs
  (`openai`, `ollama`, and `lmstudio`) are reserved and cannot be overridden." Project config ignores providers:
  "put provider, notification, and telemetry keys in user-level config instead." Window: `model_context_window` [S4].
- Kit fit [I]: local small-tier candidates (`qwen3.5:9b-q4_K_M`, `gemma4:12b-it-q4_K_M`, `gpt-oss:20b`) use `on`/`off`
  effort words; their mapping to `model_reasoning_effort` is undocumented [U]. Subagents inherit the provider (S3).

## 4. Gaps and risks

- **Path guard is open** [I]: shared build files and `may_write` scope are unguarded; only the sandbox's protected
  paths hold. Parsing `apply_patch`'s `tool_input.command` into paths would close it: new code, outside L2.
- **Owner `ask` fails open** [M S6]; **schema fit** [U]: kit schemas target `round_output.py`, not structured output.
- **Per session, not per role** [M S3]: tools, sandbox, MCP and provider come from the parent; a contract's tool
  list is prose only (as on pi), and local and hosted roles need separate `codex exec` runs.
- **Budget and subagent identity** [U]: need `agent_type`/`agent_id` in PreToolUse on 0.154.0; S6: "The linked
  `main` branch schemas may include hook fields that are not in the current release."
- **Hook trust is per hash** [M S6]: each kit update needs a new `/hooks` review; untrusted hooks are skipped, so a
  headless `codex exec` may run with no guards [I].
- **Router defaults to Claude** [I code]; **catalog drift** (`gpt-6.1-sol`, `gpt-6-luna` absent locally, openai.md §3).
- **`model-tiers.json` `harnesses.codex-cli`** lists `sandbox` and `mcp_servers` as agent fields and budget "to be
  verified" (`03-tools/config/model-tiers.json:1077-1091@44bd74c`); S3 contradicts the first two. Fix in H4.

## 5. Sources (read 2026-10-18; HTTP from `curl -sL -w '%{http_code}'`)

| ID | URL | HTTP |
|---|---|---|
| S1 | https://developers.openai.com/codex/llms.txt (redirects to https://learn.chatgpt.com/docs/llms.txt) | 200 |
| S2 | https://learn.chatgpt.com/docs/agent-configuration/agents-md.md | 200 |
| S3 | https://learn.chatgpt.com/docs/agent-configuration/subagents.md | 200 |
| S4 | https://learn.chatgpt.com/docs/config-file/config-advanced.md | 200 |
| S5 | https://learn.chatgpt.com/docs/config-file/config-reference.md (https://developers.openai.com/codex/config-reference redirects here) | 200 |
| S6 | https://learn.chatgpt.com/docs/hooks.md | 200 |
| S7 | https://learn.chatgpt.com/docs/extend/mcp.md | 200 |
| S8 | https://learn.chatgpt.com/docs/build-skills.md | 200 |
| S9 | https://learn.chatgpt.com/docs/agent-approvals-security.md | 200 |
| S10 | https://learn.chatgpt.com/docs/agent-configuration/rules.md | 200 |
| S11 | https://api.github.com/repos/openai/codex/contents/docs; https://raw.githubusercontent.com/openai/codex/main/docs/{config,agents_md,exec,skills}.md (stubs pointing to S2-S5) | 200 each |
| S12 | https://raw.githubusercontent.com/openai/codex/main/codex-rs/hooks/schema/generated/pre-tool-use.command.input.schema.json | 200 |
| S13 | https://docs.ollama.com/integrations/codex.md | 200 |
| S14 | https://lmstudio.ai/docs/integrations/codex (HTML, text extracted) | 200 |
| L1 | local `codex-cli 0.154.0` at `/opt/homebrew/bin/codex`: `--help`, `exec --help`, `mcp --help`, `mcp add --help`, `features --help`, `features list` | n/a |

Also fetched, not cited (200 each): `config-basic.md`, `config-sample.md`, `permission-modes.md`, `models.md`,
`customization/overview.md`. Failed: https://learn.chatgpt.com/docs/noninteractive.md 404; https://lmstudio.ai/docs/developer/openai-compat/codex
404. No third-party source. Quote check: 37 of 37 verbatim quotes found, whitespace-normalized, in the fetched files or L1.
