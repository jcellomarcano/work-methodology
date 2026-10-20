# Runtime adapters · v1

Cap: 120 lines. Scripts: `03-tools/bin/install.sh`, `install-claude.sh`, `install-pi.sh`,
`03-tools/lib/render_agents.py`, `03-tools/lib/engram_bridge.py`, `03-tools/hooks/pi/metodo-hooks.ts`.

## 1. Purpose: one source, many runtimes

The kit has exactly one copy of each thing it knows: roles in `01-roles/agents/`, skills in
`02-skills/`, checkers in `03-tools/lib/`, the MCP server in `03-tools/mcp/server.py`. A runtime
adapter never holds a second copy. It renders that source into the shape a given agent host reads,
and `install.sh` picks which adapters run.

The consequence to keep: a rule changes in one file, and every runtime gets it on the next install.
A rule that has to be written twice is a rule that will be true in one runtime and stale in the other.

## 2. Support matrix

`[Measured]` means run on this machine on 15-sep-2026 against a throwaway git repo with pi v0.85.1 and
gentle-ai 2.9.1 installed. `[Tested]` means a kit test asserts it. `[Unverified]` means the code is written and untested. `[Harness]` means
driven through node with a fake pi API by `03-tools/tests/test_pi_extension.py` on 15-oct-2026: the
extension's logic is proven, a live pi delivering the same event fields is not.

| | Claude Code | pi | pi + gentle-ai |
|---|---|---|---|
| Agents | `.claude/agents/generic-*.md` with the Claude frontmatter [Measured] | `.pi/agents/generic-*.md`, tools mapped to pi built-ins [Measured, rendered and installed; no role run end to end] | same, side by side with `~/.pi/agent/agents/` [Unverified] |
| Skills | `.claude/skills/<name>/` [Measured] | `.pi/skills/<name>/`, Agent Skills standard [Measured, installed; `allowed-tools` is ignored by pi] | same [Unverified] |
| MCP tools | `.mcp.json`, names `mcp__metodo__*` [Measured] | same `.mcp.json` plus `toolPrefix: "mcp"` in `.pi/mcp.json` [Measured, `mcp__metodo__docs_lint` called and returned] | same [Unverified] |
| Hooks and guards | six hooks in `.claude/settings.local.json` (no Stop hook since D3) [Tested] | `.pi/extensions/metodo-hooks.ts` runs the same Python with the same matchers (`HOOK_MATRIX`, checked against `hooks.settings.json`) [Measured: a write to `build.gradle` was blocked and ledgered; Harness: matrix parity] | kit extension only; gentle-ai's hooks live in `~/.claude/settings.json` and are untouched [Unverified] |
| Receipt gate | `mcp__metodo__receipt_start/finalize/acknowledge` reach `guard_gates.py` [Tested, `test_hooks.py`] | same three names, plus the generic `mcp` proxy when an input string names a receipt tool; a subagent is denied [Harness; Unverified on a live pi] | same as pi [Unverified] |
| Subagent budget | `budget.py` denies the call past `max_tool_calls` [Measured] | same script on every tool call, one counter per subagent process; needs the role (section 2.1), else uncapped [Harness; Unverified on a live pi] | same as pi [Unverified] |
| Output check on close | `validate_subagent_output.py` on SubagentStop, blocks once [Tested, `test_hooks.py`] | same script at `agent_end` in a subagent process; a FAIL is ledgered as `invalid-unenforced`, because pi cannot send the subagent back [Harness; Unverified on a live pi] | same as pi [Unverified] |
| Visible WARN | scope, delivery and budget warns print `additionalContext` `METODO-WARN <kind>: <fix>` (≤ 80 tok), never a decision [Tested, `test_hooks.py`; live support Unknown] | the line is queued and sent as the next `before_agent_start` message, not with the tool call; not visible to the model [Unverified] [Harness] | same as pi [Unverified] |
| Bash outcome log | PostToolUse Bash runs `guard_gates.py` [Tested, `test_hooks.py`] | same, on `tool_result` [Harness; Unverified on a live pi] | same as pi [Unverified] |
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
bin/install.sh <repo> --runtime pi             # pi only
bin/install.sh <repo> --runtime claude         # claude only
bin/install.sh <repo> --tools ~/<instance>     # point at a synced tools instance
bin/install.sh <repo> --engram-project <name>  # fix the engram project name
```

`--runtime claude` delegates to `install-claude.sh` unchanged. `--runtime pi` calls `install-pi.sh`,
which renders the roles with `render_agents.py`, copies the same skill list (read out of
`install-claude.sh`, so the two cannot drift), writes the shared `.mcp.json` with `mcp_config.py`,
adds the `.pi/mcp.json` prefix override, installs the guards extension, and appends everything to
`.git/info/exclude`.

`bin/init.sh <repo>` wraps `install.sh` with the instance, adaptation, baseline, doctor and smoke.
Unplug with `bin/init.sh <repo> --uninstall` (or `install.sh <repo> --uninstall`): only files byte-identical
to the kit's render go, a modified one stays; `doctor.sh <repo> --absent` proves nothing is left.

pi loads `.pi/extensions` only after the project is trusted. Interactively that is `/trust`;
non-interactively it is `--approve` (`-a`) for one run, or `defaultProjectTrust: "always"` in
`~/.pi/agent/settings.json`.

## 4. Living beside gentle-ai

gentle-ai owns the files listed in `~/.pi/agent/gentle-ai/managed-assets.json` and the hooks in
`~/.claude/settings.json`. The kit writes to neither. Every path an installer touches is inside the
target repo: `.claude/`, `.pi/`, `.mcp.json`, `.git/info/exclude`. Nothing is installed globally, so
removing the kit from a repo cannot take a gentle-ai asset with it.

Two receipt systems in one repo need one of them to be the authority, and that is a decision, not a
merge. It lives in `config/project.json` as `rdd.review_authority`:

- `"kit"` (the default): the kit receipt is the review authority. Its verdict is what the gates read.
- `"gentle-ai"`: gentle-ai's lineage decides delivery, and the kit receipt stays as the ledger of the
  kit's own checkers. It still records what ran and what it found; it just does not decide.

Read the switch with `gentle-ai review mode status`, which changes nothing. When it says off, nothing
is running on the gentle-ai side and `"kit"` is the honest value. `session_start_status.py` prints the
chosen authority on every session start, so the answer is on screen before the first edit.

## 5. Memory with engram

`engram_bridge.py` shells `engram save` and returns True or False. It is a no-op returning False when
the binary is absent or `memory.enabled` is false in `config/project.json`, and a failure there never
reaches the caller. The project name comes from `memory.engram_project`, then `ENGRAM_PROJECT`, then
the repo folder's name. `METODO_MEMORY=off` in the environment beats an enabled config; the kit's own
test suite sets it, so a receipt or handoff test never reaches the real database.

Two call sites save on their own:

| Moment | Topic key | What it holds |
|---|---|---|
| a receipt is finalized | `metodo/receipt/<tree>` | verdict, reasons, round, tier, receipt path |
| a handoff is written | `metodo/handoff/<round>/<role>` | who handed to whom, the summary, the artifact |

engram overwrites the note that carries the same topic key. So a topic key holds the latest state of
that thing and never its history. That is the point: `out/` is the audit trail and engram is the index
into it. When you need what the second capture said before the third one landed, read the round
directory, not the note.

Two calls stay manual, because they are judgment and not bookkeeping:

- `mem_context` at session start, to find out what past sessions concluded about this repo.
- `mem_save` for a decision, once it is made. The bridge saves what a script produced; a decision
  someone reached in conversation has no script to hang off, so it has to be saved by hand.
