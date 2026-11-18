# agy adapter (Google Antigravity CLI) · v1

Cap: 80 lines. Scripts: `03-tools/bin/install-agy.sh`, `03-tools/hooks/agy/` (`bridge.py`, `hooks.json`),
`03-tools/lib/render_agents.py --target agy`. Principle: `runtime-adapters.md` section 1. Owner decision:
L1 of `odd/tasks/agy-adapter.md`, newer than L2 of `odd/tasks/harness-guides.md` (by hand, no installer).
Tags: `[Measured]` = seen on agy 1.4.7 on 2026-10-26 with the kit's Spanish tree (L3 and L5 there), not
re-measured on this tree; `[Tested]` = a test of this tree asserts it; `[Unknown]` = nobody measured it.

## 1. Shape: one workspace plugin

agy loads a plugin from `<repo>/.agents/plugins/<name>/`, and a plugin is the only per-repo place where it
starts an MCP server [Measured], so the kit lands in one folder (manifest `plugin.json`), nothing in `~/.gemini/`:

| In `.agents/plugins/metodo/` | Holds |
|---|---|
| `agents/generic-*.md` | `render_agents.py --target agy`: `name`, `description`, `model` as a tier (an opus model → `pro`, haiku → `flash`, else `inherit`), the body, the core, the contract as prose (it names `**/.agents/**`), the role marker; no tool list [Tested, `test_render_agents.py`] |
| `contracts/generic-*.contract.json` | each role's contract, byte for byte: the guards read a role's cap and `may_spawn` here when the repo has no `.claude/agents` and the tools root is an instance [Tested, `test_install_agy.py`] |
| `skills/<name>/` | the `SKILLS` list read out of `install-claude.sh`, so the runtimes cannot drift |
| `hooks.json` | `hooks/agy/hooks.json`: SessionStart, PreToolUse, PostToolUse and Stop all call `bridge.py` |
| `mcp_config.json` | the `metodo` stdio server for this repo; agy names it `metodo_metodo` [Measured] |
| `rules/AGENTS.md` | how the kit's tool names read on agy [Measured: the model called the kit server from it] |

agy is opt-in: `install.sh --runtime agy` (or `init.sh --runtime agy`); `all` stays claude and pi. agy reads
no `.mcp.json`, so the claude/pi shared entry is untouched. Install is idempotent and adds the plugin to
`.git/info/exclude`; uninstall removes only files byte-identical to the render. `doctor.sh --runtime agy`
checks the agy agents, role contracts, skills, hooks and MCP server, and `--absent` covers agy.

## 2. The hook bridge

`bridge.py <event>` turns agy's stdin (camelCase, `toolCall{name,args}`) into the stdin Claude Code sends,
runs the scripts `hooks.settings.json` maps to that tool (read at run time) and answers in agy's protocol.
Every entry of that file has a row here or a stated exemption [Tested, `test_agy_bridge.py`].

| agy tool or event | Runs | As |
|---|---|---|
| `write_file`, `edit_file`, any other write-like tool with a `Path` | `guard_paths.py`; after it `touched_paths.py`, `output_author.py` | `Write` or `Edit`, `Path` → `file_path` |
| `run_command` | `guard_gates.py`, before and after | `Bash`, `CommandLine` → `command` |
| `call_mcp_tool` on the kit server | `guard_gates.py` on the receipt tools; `output_author.py` after `output_write` | `mcp__metodo__<ToolName>`, `Arguments` as the input |
| `invoke_subagent` | `guard_spawn.py`, the launch gate | a `Task` launch: `TypeName` → `subagent_type`, `Prompt` → `prompt`; `Role` is carried and judged by nothing |
| every tool call | `budget.py` | with the subagent's resolved role and conversation |
| Stop in the owner's conversation | `done_gate.py` | the kit's Stop; the last reply is read from the transcript; `hooks.json` gives Stop 35 s because the done gate is a 30 s hook |
| Stop inside a subagent | `validate_subagent_output.py`, then `done_gate.py` | the kit's SubagentStop, which agy does not have |
| SessionStart in the owner's conversation | `session_start_status.py` | source `startup`; the status reached the model as a system message [Measured] |
| exempt | `tool_output_filter.py` and `bench_queue.py` never run | no measured field carries or replaces a command's output; agy has no SessionEnd event, and the benchmark reads Claude Code transcripts, which an agy session does not write |

Decisions [Measured, three spike runs on a scratch repo]: an empty stdout is neutral; `{}` denies (a
decision is required); a nonzero exit fails the tool; `allow` would skip agy's own permissions. So on a tool
call the bridge prints only a deny, a `force_ask` for an owner gate (a plain `ask` let an edit through in
accept-edits mode; inside a subagent nobody can answer, so it becomes a deny that says to report it), or
nothing, and always exits 0. A script's stdout is read line by line, so a warn line beside a deny stays a
deny [Tested]. On Stop a script's `block` becomes `continue`, the send-back of agy's own docs [Tested].

Who the subagent is: agy runs it as its own conversation and its hooks carry no agent type [Measured]. A
launch the gate lets through is recorded with its `TypeName` and prompt; the child's transcript opens with
a system message `sender=<parent> ... content=<prompt>`, and the pair names the role [Measured:
`generic-mechanic` resolved, its output check ledgered on close]. A sender with no recorded call, or one
that does not parse, is still a subagent (`agy-subagent`: subagent denies apply, contracts do not) [Tested].

## 3. Limits

| Limit | Why |
|---|---|
| The kit's warn lines do not reach the model | no output that reaches the model without a decision was measured (`{}` denies) [Unknown], so `METODO-WARN` lines and the done gate's warn-first `DONE-GATE:` block stay in the ledger only; the model sees a deny, an owner prompt, a BLOCK-mode send-back and the start status, nothing else |
| No goal anchor on compact or resume | agy's SessionStart stdin names no source, so every start is sent as `startup` |
| No tool-output filter, no session measurement | the two exemptions above; agy has no SessionEnd [Measured], so its sessions are never queued for the benchmark |
| A live subagent write deny is not reachable on agy 1.4.7 | the custom subagent got read tools and `call_mcp_tool`, no `edit_file` [Measured]; the deny on `.agents/` and build files is [Tested] through the bridge only |
| The launch gate inside a subagent is [Tested] only | whether an agy subagent has `invoke_subagent` at all is [Unknown] |
| Headless MCP calls are denied | under `agy -p` agy's own permission denied the kit's `call_mcp_tool` [Measured]; `--mode auto` was unavailable for the measuring account [Measured]; see section 4 |
| This tree's bridge and installer never ran against a live agy | no live send-back on Stop was measured on either tree; the launch gate, the done gate on Stop and the line-by-line parse are [Tested] in `test_agy_bridge.py`; every measurement here used the Spanish tree, where `init.sh --runtime agy` gave doctor PASS, smoke PASS and `ready_for_benchmark` true [Measured] |
| Open advisories (L7, Spanish tree, not rechecked here) | the bridge's identity cache is writable by a subagent with a shell; a tool that names its file with a key other than `Path` is not gated as a write; `--uninstall` with the default `all` leaves an agy plugin; `--absent --runtime agy` does not check the exclude line |
| The Antigravity App | only the CLI was measured; whether the App loads the workspace plugin is [Unknown] |

## 4. What only the owner can do

- Start agy in the repo again after install: a new plugin folder loads on the next start.
- Decide where writer roles run. With no `edit_file` in a subagent, `generic-proposer` and
  `generic-mechanic` report a diff and the main session applies it, under the same guards.
- Allow the kit's MCP tools once. agy asks before an MCP call and in a headless run nobody can answer, so it
  is denied until an allow rule exists: in agy's settings under `~/.gemini/` (form `mcp(<server>/*)`), or for
  one run with `--settings '{"permissions":{"allow":[...]}}'` (agy 1.5.8 help; never run here). The kit writes neither.
