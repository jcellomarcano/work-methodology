# Runtime adapters · v1

Cap: 120 lines. Scripts: `03-tools/bin/install.sh`, `install-claude.sh`, `install-pi.sh`, `install-agy.sh`,
`03-tools/lib/render_agents.py`, `03-tools/lib/engram_bridge.py`, `03-tools/hooks/pi/metodo-hooks.ts`, `hooks/agy/`.

## 1. Purpose: one source, many runtimes

The kit has exactly one copy of each thing it knows: roles in `01-roles/agents/`, skills in `02-skills/`,
checkers in `03-tools/lib/`, the MCP server in `03-tools/mcp/server.py`. A runtime adapter never holds a
second copy. It renders that source into the shape a given agent host reads, and `install.sh` picks which
adapters run. So a rule changes in one file and every runtime gets it on the next install; a rule written
twice ends up true in one runtime and stale in the other.

## 2. Support matrix

`[Measured]` means run on this machine on 15-sep-2026 against a throwaway git repo with pi v0.85.1 and
gentle-ai 2.9.1 installed. `[Tested]` means a kit test asserts it. `[Unverified]` means the code is written and untested. `[Harness]` means
driven through node with a fake pi API by `03-tools/tests/test_pi_extension.py` on 15-oct-2026: the
extension's logic is proven, a live pi delivering the same event fields is not.
agy (Google Antigravity CLI) is a third, opt-in adapter with its own matrix, limits and evidence: `agy-adapter.md`.

| | Claude Code | pi | pi + gentle-ai |
|---|---|---|---|
| Agents | `.claude/agents/generic-*.md` with the Claude frontmatter [Measured] | `.pi/agents/generic-*.md`, tools mapped to pi built-ins [Measured, rendered and installed; no role run end to end] | same, side by side with `~/.pi/agent/agents/` [Unverified] |
| Skills | `.claude/skills/<name>/` [Measured] | `.pi/skills/<name>/`, Agent Skills standard [Measured, installed; `allowed-tools` is ignored by pi] | same [Unverified] |
| MCP tools | `.mcp.json`, names `mcp__metodo__*` [Measured] | same `.mcp.json` plus `toolPrefix: "mcp"` in `.pi/mcp.json` [Measured, `mcp__metodo__docs_lint` called and returned] | same [Unverified] |
| Hooks and guards | ten hooks in `.claude/settings.local.json` (Stop and SubagentStop run only `done_gate.py`; reply lint off since D3; SessionEnd runs `bench_queue.py`, which queues the session for the benchmark, a Claude Code only measurement) [Tested] | `.pi/extensions/metodo-hooks.ts` runs the same Python with the same matchers (`HOOK_MATRIX`, checked against `hooks.settings.json`) [Measured: a write to `build.gradle` was blocked and ledgered; Harness: matrix parity]; the extension does not carry the SessionEnd entry, so a pi session is never queued or measured | kit extension only; gentle-ai's hooks live in `~/.claude/settings.json` and are untouched [Unverified] |
| Receipt gate | `mcp__metodo__receipt_start/finalize/acknowledge` reach `guard_gates.py` [Tested, `test_hooks.py`] | same three names, plus the generic `mcp` proxy when an input string names a receipt tool; a subagent is denied [Harness; Unverified on a live pi] | same as pi [Unverified] |
| Launch gate | `guard_spawn.py` on `Task\|Agent`: a kit role launching outside `may_spawn` is denied; a launch without a goal contract warns or blocks [Tested, `test_hooks.py`] | same script and matcher in `HOOK_MATRIX` [Harness: matrix parity; which pi tool launches a subagent is Unverified] | same as pi [Unverified] |
| Subagent budget | `budget.py` denies the call past `max_tool_calls` [Measured] | same script on every tool call, one counter per subagent process; needs the role (section 2.1), else uncapped [Harness; Unverified on a live pi] | same as pi [Unverified] |
| Output check on close | `validate_subagent_output.py` on SubagentStop, blocks once [Tested, `test_hooks.py`] | same script at `agent_end` in a subagent process; a FAIL is ledgered as `invalid-unenforced`, because pi cannot send the subagent back [Harness; Unverified on a live pi] | same as pi [Unverified] |
| Visible WARN | scope, delivery, launch and budget warns print `additionalContext` `METODO-WARN <kind>: <fix>` (≤ 80 tok), never a decision [Tested, `test_hooks.py`; live support Unknown] | the line is queued and sent as the next `before_agent_start` message, not with the tool call; not visible to the model [Unverified] [Harness] | same as pi [Unverified] |
| Done gate | `done_gate.py` on Stop and on writer SubagentStop: a done claim runs `done_check`; the `DONE-GATE:` block goes to `systemMessage` (warn); a BLOCK-mode rule sends back once per worktree, then `done-unproven`; waiver: `bin/done-waive.sh` (owner gate) [Tested, `test_done_gate_hook.py`; live Unknown] | at `agent_end`, record-only; the owner's block is queued for the next turn [Harness] | same as pi [Unverified] |
| Bash outcome log | PostToolUse Bash runs `guard_gates.py` [Tested, `test_hooks.py`] | same, on `tool_result` [Harness; Unverified on a live pi] | same as pi [Unverified] |
| Tool-output filter | over `context.tool_output_max_tokens` (2000) `tool_output_filter.py` saves the output to `out/hooks/<session>/outputs/<seq>.txt` and swaps stdout via `updatedToolOutput` for head, tail and every error line [Tested; live Unknown] | in the matrix, record-only: no output in the payload, nothing swapped [Harness] | same as pi [Unverified] |
| Review receipt | `out/rdd/<tree>.receipt.json`, the review authority [Measured] | same files, same scripts [Unverified on pi] | receipt plus `rdd.review_authority` (section 4) [Unverified] |
| Memory | `engram_bridge.py` on receipt and handoff [Measured: real notes landed in engram from both call sites] | same bridge, same call sites [Unverified on pi] | same bridge [Unverified] |

### 2.1 Who the subagent is, on pi

gentle-pi runs each subagent as its own pi process with `GENTLE_PI_AGENTS_CHILD=1` [Measured in a
gentle-pi child's environment, 15-oct-2026]. The extension derives the rest; nothing else in the
environment names the role (the child's variables carry the session and tools, not the agent name).

- `agent_id` is `pi-<pid>-<load time>`, computed once per process: stable for one subagent, distinct
  for two, even when both share a session id (`pi-ephemeral` without a session file).
- `agent_type` is `METODO_AGENT_TYPE` if the spawner sets it; else the `<!-- metodo-role: <name> -->`
  line `render_agents.py` appends to every pi agent, read from `before_agent_start`'s `systemPrompt`;
  else `pi-subagent`, which keeps the subagent denies but has no contract [Harness; whether a live pi
  passes `systemPrompt` there is Unverified].
- A subagent's ledger lands under its own session id, not the owner's [Unverified on a live pi].

## 3. Install

```bash
bin/install.sh <repo>                          # claude and pi
bin/install.sh <repo> --runtime claude|pi|agy  # one runtime; agy is never part of the default (agy-adapter.md)
bin/install.sh <repo> --tools ~/<instance>     # point at a synced tools instance
bin/install.sh <repo> --engram-project <name>  # fix the engram project name
```

`--runtime claude` delegates to `install-claude.sh`. `--runtime pi` calls `install-pi.sh`, which renders the
roles with `render_agents.py`, copies the same skill list (read out of `install-claude.sh`, so the two cannot
drift), writes the shared `.mcp.json` with `mcp_config.py`, adds the `.pi/mcp.json` prefix override and
installs the guards extension. Each installer appends the paths it wrote to `.git/info/exclude`.

`bin/init.sh <repo>` wraps `install.sh` with the instance, adaptation, baseline, bench step, doctor and smoke.
Unplug with `bin/init.sh <repo> --uninstall` (or `install.sh <repo> --uninstall`): only files byte-identical
to the kit's render go, a modified one stays; `doctor.sh <repo> --absent` proves nothing is left.

pi loads `.pi/extensions` only after the project is trusted: interactively `/trust`; non-interactively
`--approve` (`-a`) for one run, or `defaultProjectTrust: "always"` in `~/.pi/agent/settings.json`.

## 4. Living beside gentle-ai

gentle-ai owns the files listed in `~/.pi/agent/gentle-ai/managed-assets.json` and the hooks in
`~/.claude/settings.json`. The kit writes to neither. Every path an installer touches is inside the
target repo: `.claude/`, `.pi/`, `.agents/plugins/metodo/`, `.mcp.json`, `.git/info/exclude`. Nothing is installed globally, so
removing the kit from a repo cannot take a gentle-ai asset with it.

Two receipt systems in one repo need one of them to be the authority, and that is a decision, not a
merge. It lives in `config/project.json` as `rdd.review_authority`:

- `"kit"` (the default): the kit receipt is the review authority. Its verdict is what the gates read.
- `"gentle-ai"`: gentle-ai's lineage decides delivery, and the kit receipt stays as the ledger of the
  kit's own checkers. It still records what ran and what it found; it just does not decide.

Read the switch with `gentle-ai review mode status`, which changes nothing. When it says off, nothing
is running on the gentle-ai side and `"kit"` is the honest value. `session_start_status.py` prints the
chosen authority on every session start, so the answer is on screen before the first edit.
On compact and resume it adds a goal anchor (task doc, open T# + S#, last receipt; ≤ 120 tokens).

## 5. Memory with engram

`engram_bridge.py` shells `engram save` (True or False) and, for `--recall`, `engram search`. Both are no-ops when
the binary is absent or `memory.enabled` is false in `config/project.json`, and a failure there never
reaches the caller. The project name comes from `memory.engram_project`, then `ENGRAM_PROJECT`, then
the repo folder's name. `METODO_MEMORY=off` in the environment beats an enabled config; the kit's own
test suite sets it, so a receipt or handoff test never reaches the real database.

Two call sites save on their own:

| Moment | Topic key | What it holds |
|---|---|---|
| a receipt is finalized | `metodo/receipt/<tree>` | verdict, reasons, round, tier, receipt path |
| a handoff is written | `metodo/handoff/<round>/<role>` | who handed to whom, the summary, the artifact |

engram overwrites the note that carries the same topic key: a key holds the latest state of that thing,
never its history. `out/` is the audit trail and engram is the index into it; for what the second capture
said before the third landed, read the round directory, not the note.

Reads and manual saves follow `lib/engram_rule.py --phase start|resume|compact|task`, first row wins: kill
switch or no binary, off; subagent, never (the parent forwards); sensitive or unresolved project, 1 search
with an explicit project, no saves; compacted, `mem_context` compact ≤ 4096 bytes once; resume, task doc
first, then that plus ≤ 2 `mem_search` × 5; new multi-session task, 1 search; trivial, no reads; else 1
search only if the prompt names earlier work. Off after 20 sessions with recall-used < 0.2. Multi-agent:
the orchestrator searches and saves (`mem_save`: a decision or a verified learning, one topic key each); a
worker reads only the `engram:<topic-key>` or `engram:#<id>` entries of its `INPUTS` and writes nothing:
learnings go in its output. Session start prints ≤ 3 pointers (`#id (kind) title`, never the body) off
trunk, via `engram_bridge.py --recall`. A recalled file, flag or number is Assumed until re-checked.
