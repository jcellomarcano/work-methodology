# Live session probe: the kit under real Claude Code, pi and Antigravity sessions

Date 2026-11-13. Kit `main@621ed86`. One throwaway Python repo (two source files, one commit), its own tools
instance and audit folder, all under a temp folder that is gone after the probe. Harness versions: Claude Code
2.1.323, pi 1.3.0, agy 1.4.7. Every line below was observed in this probe unless its tag says otherwise. The raw
streams were not kept; what is quoted here is what remains.

## What ran

| Runtime | Install | Live session | Result |
|---|---|---|---|
| Claude Code | `init.sh <repo> --runtime claude --no-fetch`: doctor PASS, smoke PASS | two `claude -p` sessions, model sonnet, `--setting-sources project,local` | works end to end [Tested] |
| pi | `init.sh <repo> --runtime pi --no-fetch --no-smoke --no-baseline`: doctor PASS | three `pi -p` runs | the extension and the session-start status load; no model reply, the owner's pi login had expired [Tested] |
| Antigravity | `init.sh <repo> --runtime agy ...`: doctor PASS | one `agy -p --mode accept-edits` session | hooks run through the bridge on read and edit; the shell step was denied by agy's own headless permission [Tested] |
| all three | `init.sh <repo> --runtime <rt> --uninstall` | | repo back to its own files, `.git/info/exclude` cleared, instance kept [Tested] |

Spend: USD 0.13 and USD 0.27 for the two Claude Code sessions (the harness's own figure); agy reports tokens and
no cost; pi spent nothing.

## Claude Code: what was seen working [Tested]

- 12 agents and 17 skills listed by the session; the `metodo` MCP server connected from `.mcp.json` in headless
  mode.
- Hooks fired with exit 0 on every event of the session: `session_start_status` (the status line reached the
  model), `budget`, `guard_paths`, `guard_gates`, `tool_output_filter`, `touched_paths`, `output_author`,
  `done_gate`. `touched.jsonl` held exactly the two files the session wrote.
- `guard_spawn` on a subagent launched with a one-line prompt: `METODO-WARN spawn-no-goal: ... launch without a
  goal contract (missing: ROLE, OBJECTIVE, SPECS, ACCEPTANCE, INPUTS, SCOPE, ALREADY READ, CONSTRAINTS, OUTPUT,
  STOP, BUDGET, EVIDENCE)`. Warn mode: the launch went ahead.
- `gate-push` on `git push`: `METODO-WARN gate-push: no approved receipt for tree <sha> (receipt: none); run
  receipt-review first, or tell the owner this delivers without review.`
- `mcp__metodo__bench_report` started a job and wrote `out/bench/report/phase1-baseline.md` and `.json`.
- The `SessionEnd` hook queued each session and the row was measured without any command: `bench.sh status`
  read `sessions_measured: 2, queue_left: 0`; the stored cost of session one (0.13117) equals the harness's
  (0.1311699); session two's row counts one subagent, one `metodo` MCP call and two hook warnings.
- `doctor.sh --runtime claude` after the sessions: `bench.used` PASS, `bench.wired` PASS.

## Findings

| # | Finding | Evidence | Tag |
|---|---|---|---|
| F1 | The Claude Code install leaves `.claude/agents`, `.claude/skills` and `.claude/metodo-settings-keys.json` untracked and not excluded; only `.mcp.json` goes to `.git/info/exclude`. A plain `git add -A && git commit` by the agent committed 46 kit files, 4306 lines, into the user's repo. The pi and agy installs do exclude their folders. | `git status` after install: `?? .claude/`; commit output of session two | Tested |
| F2 | pi drops three skills: `necessary-comment`, `receipt-review`, `review-comment`. Their `description:` holds an unquoted `: `, which is not valid YAML; a strict parser answers "mapping values are not allowed here" for exactly these three and no other. Claude Code loads them anyway. The doctor's `pi.skills` reads PASS because it checks the files, not the parse. | pi listed 14 of 17 kit skills; `yaml.safe_load` on the 17 front matters | Tested (the drop), Inferred (the cause) |
| F3 | A headless `pi -p` without `--approve` loads nothing of the kit, silently: no extension, no skill, no hook log, while the doctor reads PASS. The rule is written (`00-principles/runtime-adapters.md:71`); nothing at run time says it. | first pi run: 13 skills, none of the kit, no folder under `out/hooks/` | Tested |
| F4 | With `--approve`, the pi session still had no `mcp__metodo__*` tool. `pi list` shows no MCP package on this machine, and `pi.mcp` reads PASS on the config file alone. | tool list of the approved run: 31 tools, none from `metodo` | Tested (absence), Unknown (whether a package is all that is missing) |
| F5 | `doctor.sh <repo> --tools <instance>` without `--runtime` checks `all` and reads FAIL (four `pi.*` checks) on a repo installed for Claude Code only. `AGENTS.md` gives that command as the check. | doctor output after the Claude-only install | Tested |
| F6 | `run-meta.json` of every session stores `started_at` in local time with no zone, and the machine's host name. | the file of each session | Tested |
| F7 | `done_gate` stayed silent at `Stop` in warn mode, in a session that changed code with no receipt open. | hook output empty, exit 0 | Tested (silence), Unknown (whether intended) |
| F8 | Under agy the push gate was not reached: agy denied `run_command` in headless mode before any `git push`. | agy stderr: "a tool required the \"command\" permission that headless mode cannot prompt for" | Tested |

## Fixed after the probe (same day, the owner's go-ahead)

- F1: `install-claude.sh` writes one exclude line per path it installs (the `generic-*` agents, each kit skill,
  `settings.local.json`, `metodo-settings-keys.json`) and drops each line on uninstall once its path is gone; an
  agent or skill of the repo's own stays visible to git. [Tested: `03-tools/tests/test_install_claude.py`]
- F2: the three descriptions are quoted; a test fails on any skill or agent front matter with an unquoted `: `
  or ` #`. [Tested: same file, `FrontMatterIsStrictYamlTests`]
- F5: without `--runtime` the doctor checks what is installed and says so in `runtime_source`; an agy plugin
  beside claude or pi is named in `also_installed`. [Tested: `03-tools/tests/test_doctor.py`]
- Found while fixing: agy updated itself from 1.4.7 to 1.5.8 on the day of the probe (`agy --version` before and
  after), and the 1.5.8 `agy plugin validate --strict` fails a manifest with no version. `hooks/agy/plugin.json`
  now carries one. [Tested: `03-tools/tests/test_install_agy.py`] The adapter's other facts are still the
  1.4.7 measurements of `00-principles/agy-adapter.md`.
- Independent verifier on the four changes: two blockers, both corrected with a test. An exclude file with no
  final newline had its last pattern glued to the first kit line (now guarded in the three installers); and a
  broken `.claude/settings.local.json` beside pi read as "claude not installed", so the default doctor said PASS
  (detection now also counts the kit's `generic-*` agents). [Tested: `test_install_claude.py`,
  `test_install_agy.py`, `test_doctor.py`]
- F3, F4, F6, F7 and F8 are open.

## Not tested

- Any gate in block mode, on any runtime (the instance ran in the default `warn`).
- pi with a model reply: tool gates, the done gate and the MCP tools under pi.
- agy shell commands, subagents and the done gate.
- An interactive session of any runtime, and Codex or Gemini CLI.
- A session with the user's global settings loaded (the Claude Code runs used project and local settings only).
- The receipt loop driven by a live agent (the smoke runs it by script).
