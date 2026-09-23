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
gentle-ai 2.9.1 installed. `[Unverified]` means the code is written and untested.

| | Claude Code | pi | pi + gentle-ai |
|---|---|---|---|
| Agents | `.claude/agents/generic-*.md` with the Claude frontmatter [Measured] | `.pi/agents/generic-*.md`, tools mapped to pi built-ins [Measured, rendered and installed; no role run end to end] | same, side by side with `~/.pi/agent/agents/` [Unverified] |
| Skills | `.claude/skills/<name>/` [Measured] | `.pi/skills/<name>/`, Agent Skills standard [Measured, installed; `allowed-tools` is ignored by pi] | same [Unverified] |
| MCP tools | `.mcp.json`, names `mcp__metodo__*` [Measured] | same `.mcp.json` plus `toolPrefix: "mcp"` in `.pi/mcp.json` [Measured, `mcp__metodo__docs_lint` called and returned] | same [Unverified] |
| Hooks and guards | five hooks in `.claude/settings.local.json` [Measured] | `.pi/extensions/metodo-hooks.ts` runs the same Python [Measured: a write to `build.gradle` was blocked and ledgered] | kit extension only; gentle-ai's hooks live in `~/.claude/settings.json` and are untouched [Unverified] |
| Subagent budget | `budget.py` denies the call past `max_tool_calls` [Measured] | none: pi has no per-subagent hook, so the cap travels as prose in the rendered contract [Measured, rendered] | same as pi [Unverified] |
| Review receipt | `out/rdd/<tree>.receipt.json`, the review authority [Measured] | same files, same scripts [Unverified on pi] | receipt plus `rdd.review_authority` (section 4) [Unverified] |
| Memory | `engram_bridge.py` on receipt and handoff [Measured: real notes landed in engram from both call sites] | same bridge, same call sites [Unverified on pi] | same bridge [Unverified] |

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
