# Research H3: using the kit with OpenCode

Task H3 of `odd/tasks/harness-guides.md` (S1, S3). Read 2026-10-18: opencode.ai/docs (V1 pages, "Last updated: Oct 17,
2026") and the official repo `anomalyco/opencode` (`github.com/sst/opencode` redirects there) at the installed tag
`v1.18.25`. Tags: Measured (run here), Doc [O*], Source [G*], Inferred, Unknown. Nothing was launched in OpenCode.

Local [Measured]: `which opencode` → `~/.gentle-ai/bin/opencode` (shell wrapper); `opencode --version` →
`1.18.25` (latest `v1.19.3`, 2026-10-16 [G1]). `--help` lists `mcp`, `agent`, `run`, `models`, `plugin`, `--agent`,
`--auto`, `--pure` ("run without external plugins"); `opencode run --help` adds `--variant` ("model variant
(provider-specific reasoning effort, e.g., high, max, minimal)"). Docs banner: "OpenCode v2 is now available" (§4).

## 1. Kit needs mapped to OpenCode (V1)

| Kit need | OpenCode equivalent | Support | Evidence |
|---|---|---|---|
| Roles as subagents | `.opencode/agents/<name>.md`, `mode: subagent`, file name = agent name | Supported | Doc [O2] |
| Model and effort per role | frontmatter `model: provider/id`; `variant` key [G4] or pass-through `reasoningEffort` [O2] | Supported, `variant` thin in docs | Doc + Source |
| Tool allowlist per role | per-agent `permission` (`tools` deprecated); MCP tools by wildcard `metodo_*` | Supported | Doc [O2][O3] |
| Deny shared build files, `.claude/**` | `permission.edit` path patterns → `deny`; subagents keep parent denies | Supported, untested | Doc [O3], Source [G5][G9][G10] |
| Instruction file | nearest `AGENTS.md`, else `CLAUDE.md`; extra files via `instructions` | Supported | Doc [O4], Source [G6] |
| Skills (`02-skills/`) | reads `.claude/skills/<name>/SKILL.md` and `.opencode/skills/` | Supported; `allowed-tools` Unknown | Doc [O9] |
| `metodo` MCP server | `mcp.metodo`, `type: "local"`, `command` array, `environment` | Supported; tools named `metodo_<tool>` | Doc [O5], Source [G7] |
| Pre-tool guards (`guard_paths`, `guard_gates`, `budget`) | plugin hook `tool.execute.before`; a throw blocks | Partial: plugin not written | Doc [O6], Source [G2][G3] |
| Post-tool log, SessionStart, Stop | `tool.execute.after`; events `session.created`, `session.idle` | Partial: plugin, record only | Doc [O6] |
| Subagent output check that blocks | no documented way to send a subagent back | Not supported (record only, as pi) | Inferred [O6][G2] |
| Receipt gate on `receipt_*` | hook sees `metodo_receipt_start` etc.; or `"metodo_receipt_*": ask` | Partial | Source [G3][G7], Doc [O3] |
| Subagent budget (`max_tool_calls`) | `steps` caps iterations, not tool calls | Partial | Doc [O2] |
| Router roster | `opencode run --agent --model --variant`; per-agent `model` + `variant` | Supported, manual | Measured help, Doc [O2] |
| Local models | custom provider `@ai-sdk/openai-compatible` (Ollama, LM Studio, llama.cpp) | Supported | Doc [O8][O10] |
| Memory (engram bridge) | runs inside kit scripts and MCP, not the harness | Unchanged [Inferred] | `00-principles/runtime-adapters.md` §5 |

## 2. Using the kit in a repo today (no installer)

Manual, [Unverified] end to end, inside the target repo only; list new paths in its `.git/info/exclude` (`runtime-adapters.md` §3).

**2.1 Register `metodo`** in `<repo>/opencode.json` (project config overrides global; files merge [O1]):

```json
{ "$schema": "https://opencode.ai/config.json",
  "mcp": { "metodo": { "type": "local", "enabled": true, "timeout": 10000,
    "command": ["python3", "/ABS/PATH/metodologia-de-trabajo/03-tools/mcp/server.py"],
    "environment": { "METODO_TOOLS": "/ABS/PATH/metodologia-de-trabajo/03-tools" } } } }
```

- Absolute paths: substitution is `{env:VAR}` with no default, and "If the environment variable is not set, it will be
  replaced with an empty string." [O1]. The `${VAR:-default}` of `mcp_config.py` is not OpenCode syntax.
- No `METODO_REPO`: the server's cwd defaults to the project directory and it inherits OpenCode's environment [G7,
  `mcp/index.ts` `connectLocal`]; `03-tools/mcp/registry.py:83-88` then falls back to `git rev-parse --show-toplevel`.
- `timeout`: "Timeout in ms for fetching tools from the MCP server. Defaults to 5000 (5 seconds)." [O5]; 10000 is a
  guess for a cold Python start [Inferred]. Check with `opencode mcp list` [Measured: exists; not run on a repo].
- Tool names are `sanitize(client) + "_" + sanitize(name)` [G7, `mcp/catalog.ts:119`]: `metodo_docs_lint`, not
  `mcp__metodo__docs_lint`, which role bodies and skills use; the model must map it [Inferred risk].

**2.2 AGENTS.md.** "Project rules: CLAUDE.md in your project directory (used if no AGENTS.md exists)" [O4]. The kit
installs neither: add `"instructions": ["/ABS/PATH/metodologia-de-trabajo/CONTEXT-PACK.md"]` (absolute and `~/` paths
work [G6, `session/instruction.ts:137-140`]). Skills from `install-claude.sh` in `.claude/skills/` load as-is [O9].

**2.3 One role as a subagent:** `<repo>/.opencode/agents/generic-verifier.md` ("The markdown file name becomes the
agent name. For example, review.md creates a review agent." [O2]). From `03-tools/config/model-tiers.json`: tier
`medium`, `claude-sonnet-5-5` (admitted), `effort_by_role.generic-verifier: high`; the contract gives `max_turns: 50`.

```yaml
---
description: Independent, clean-context executor - runs the battery a change card names and reports a verdict from what it actually ran, never from what others claimed.
mode: subagent
model: anthropic/claude-sonnet-5-5
variant: high
temperature: 0
steps: 50
permission: { "*": deny, read: allow, grep: allow, glob: allow, list: allow, bash: allow, edit: deny, "metodo_*": deny,
  metodo_test_sectors: allow, metodo_verify_sectors: allow, metodo_verify_commit: allow, metodo_job_status: allow,
  metodo_receipt_status: allow, metodo_receipt_capture: allow, metodo_output_write: allow, metodo_handoff_write: allow }
---
```

Body: the text after the frontmatter of `01-roles/agents/generic-verifier.md`, or `03-tools/lib/render_agents.py
--target pi 01-roles/agents/generic-verifier.md` with its frontmatter swapped for the one above (it adds the contract as
prose and the `<!-- metodo-role: ... -->` marker).
- `variant`: "Default model variant for this agent (applies only when using the agent's configured model)." [G4]; the
  V1 example in [O13] uses it; the agents page omits it and shows `reasoningEffort` passed through [O2].
- Claude 5+ ids get variants `low medium high xhigh max` [G8, `provider/transform.ts:669-672`]; the docs list only
  `high` (default) and `max` [O7]. Whether `anthropic/claude-sonnet-5-5` is listed is [Unknown]: `opencode models
  anthropic`. Subscription plugins: "Anthropic explicitly prohibits this." [O8]; use an API key.
- `steps` caps iterations, then forces a text answer [O2]; not `max_tool_calls: 40` (needs `budget.py`, 2.5). `"*": deny`
  first: "Rules are evaluated by pattern match, with the last matching rule winning." [O3] (`"*"` per agent and YAML
  flow style in frontmatter are [Inferred]).

**2.4 Deny shared build files and `.claude/**`.** `edit` gates `write`, `edit` and `apply_patch` [O2]; the pattern is
the worktree-relative path [G5, `tool/edit.ts:104`, `tool/write.ts:56`] matched with `*` → `.*` [G9]: "* matches zero
or more of any character" [O3]. So `**/*.gradle` misses a root `build.gradle`; rewrite the kit globs:

```yaml
permission:
  edit: { "*": allow, "*.gradle": deny, "*.gradle.kts": deny, "*gradle.properties": deny, "*gradle/wrapper/*": deny,
    "*buildSrc/*": deny, "*build-logic/*": deny, ".claude/*": deny, "*/.claude/*": deny }
```

Repeat the denies in the top-level `permission`: a subagent keeps "The parent session's deny rules" [G10]. "Explicit
"deny" rules are still enforced." under `--auto` [O3]. Bash is not covered (`sed -i build.gradle` passes) [Inferred].

**2.5 Python guards from a plugin.** Documented events include `tool.execute.before`, `tool.execute.after`,
`session.created`, `session.idle`; local plugins load from `.opencode/plugins/` [O6]. V1 input is `{ tool, sessionID,
callID }`, output `{ args }`, no agent name; `chat.params` input has `sessionID` and `agent` [G2,
`packages/plugin/src/index.ts:247-281`]. The hook wraps built-in, MCP and subagent calls (child sessions) [G3,
`session/tools.ts`]; a throw blocks, as in the docs' `.env` example [O6]. Sketch [Inferred, not run]:

```ts
// <repo>/.opencode/plugins/metodo-guards.ts
import { spawnSync } from "node:child_process"
const H = `${process.env.METODO_TOOLS}/hooks`, agentOf = new Map<string, string>()
const NAMES: Record<string, string> = { edit: "Edit", write: "Write", bash: "Bash", read: "Read" }
const hook = (s: string, body: unknown) => {
  const r = spawnSync("python3", [`${H}/${s}`], { input: JSON.stringify(body), encoding: "utf8", timeout: 10000 })
  try { return JSON.parse(r.stdout || "{}").hookSpecificOutput } catch { return undefined } }
export const MetodoGuards = async ({ worktree }) => ({
  "chat.params": async (input) => { agentOf.set(input.sessionID, input.agent) },
  "tool.execute.before": async (input, output) => {
    const name = NAMES[input.tool] ?? input.tool.replace(/^metodo_/, "mcp__metodo__")
    const role = agentOf.get(input.sessionID) ?? "", sub = role.startsWith("generic-")
    const scripts = /^(Edit|Write)$/.test(name) ? ["guard_paths.py", "budget.py"]
      : /^(Bash|mcp__metodo__receipt_(start|finalize|acknowledge))$/.test(name) ? ["guard_gates.py", "budget.py"] : ["budget.py"]
    for (const s of scripts) {
      const v = hook(s, { session_id: input.sessionID, cwd: worktree, hook_event_name: "PreToolUse", tool_name: name,
        tool_input: { ...output.args, file_path: output.args?.filePath }, agent_type: sub ? role : "", agent_id: sub ? input.sessionID : "" })
      if (v?.permissionDecision === "deny" || (v?.permissionDecision === "ask" && sub)) throw new Error(`metodo: ${v.permissionDecisionReason}`)
    } },
})
```

Open: an owner `ask` has no confirm path (`permission.ask` [G2] might bridge it, Unknown); `apply_patch` carries
`patchText`, not a path [G11], and replaces edit/write for `gpt-` models [G12, `tool/registry.ts:297-300`], so
`guard_paths.py` sees nothing there (the `edit` permission still applies); no `HOOK_MATRIX` parity test as on pi.

**2.6 The router's roster.** `03-tools/bin/route.sh <task.json> --as-of <date>` prints `provider`, `model`, `effort` per
role (`03-tools/lib/router.py` `result` dict, working tree). Write `model: <provider>/<model>` and `variant: <effort>` in the role file, or
launch `opencode run --agent generic-verifier --model anthropic/claude-sonnet-5-5 --variant high "<task>"` [Measured:
flags exist]. Pin every role: "subagents will use the model of the primary agent that invoked the subagent." [O2].
`model-tiers.json` has no `opencode` launch entry (H4 or later); Fable 5.1 still needs the owner's OK.

## 3. Local models in OpenCode

Ollama [O8][O10]; the model id and `limit` values are examples, `limit.context` / `limit.output` are documented keys:

```json
{ "provider": { "ollama": { "npm": "@ai-sdk/openai-compatible", "name": "Ollama (local)",
  "options": { "baseURL": "http://localhost:11434/v1" },
  "models": { "qwen3.5:9b-q4_K_M": { "name": "Qwen3.5 9B (local)", "limit": { "context": 65536, "output": 8192 } } } } } }
```

LM Studio [O8]: provider id `lmstudio`, same `npm`, `"baseURL": "http://127.0.0.1:1234/v1"`, model key as LM Studio
names it (docs example `google/gemma-3n-e4b`). llama.cpp `llama-server` [O8]: `"baseURL": "http://127.0.0.1:8080/v1"`.
`ollama launch opencode` uses an inline config and "does not overwrite ~/.config/opencode/opencode.json" [O10].
- Context: "OpenCode requires a context length of 64k or higher." [O10] vs "If tool calls aren’t working, try
  increasing num_ctx in Ollama. Start around 16k - 32k." [O8]. Set the server (`num_ctx`, `--context-length`;
  `odd/research/model-router/local.md` §3) to ≥ 64k and `limit.context` to match.
- Effort: `@ai-sdk/openai-compatible` gets variants `low medium high` sent as `reasoningEffort` [G8,
  `provider/transform.ts:930-938`]; the kit's local `off`/`on` levels have no built-in variant [Unknown mapping].

## 4. Gaps and risks

- **V2:** "Port plugins, because V1 plugin implementations do not run in V2." [O13]; V2 renames permission actions
  (`bash` → `shell`, `task` → `subagent`) and folds `variant` into `model#variant` [O13]. Section 2 is V1 only.
- **Tool names:** `metodo_*` vs `mcp__metodo__*` in roles, skills and `role_contract_validator.py`; a plugin translates.
- **Guards:** only via an unwritten TS plugin; `--pure` turns it off; a throw is the only block; no blocking output
  check. Users bypass task permissions: "Users can always invoke any subagent directly via the @ autocomplete menu,
  even if the agent’s task permissions would deny it." [O2].
- **Also:** kit globs need rewriting (2.4); `steps` ≠ `max_tool_calls`; `claude-*-5-5` availability is Unknown (2.3).

## Sources (read 2026-10-18; HTTP status from `curl -sL -w '%{http_code}'`)

| ID | URL | Status |
|---|---|---|
| O1-O9 | https://opencode.ai/docs/{config, agents, permissions, rules, mcp-servers, plugins, models, providers, skills}/ in that order | 200 each |
| O10 | https://docs.ollama.com/integrations/opencode | 200 |
| O11, O12 | https://opencode.ai/docs/{tools, cli, custom-tools, ecosystem}/ (context); https://opencode.ai/config.json (schema) | 200 each |
| O13 | https://opencode.ai/v2/docs/migrate-v1/ | 200 |
| G1, G2 | https://github.com/sst/opencode (→ anomalyco/opencode), https://api.github.com/repos/anomalyco/opencode/releases; G2 https://raw.githubusercontent.com/anomalyco/opencode/v1.18.25/packages/plugin/src/index.ts | 200 each |
| G3-G12 | same tag, `packages/opencode/src/`: G3 session/tools.ts + session/prompt.ts, G5 tool/edit.ts + tool/write.ts, G6 session/instruction.ts, G7 mcp/index.ts + mcp/catalog.ts, G8 provider/transform.ts, G10 agent/subagent-permissions.ts, G11 tool/apply_patch.ts, G12 tool/registry.ts; `packages/core/src/`: G4 v1/config/agent.ts, G9 util/wildcard.ts | 200 each |

Not used: https://opencode.ai/docs/modes/ returned 404. Raw copies in `$TMPDIR/h3opencode`, outside the repo.
