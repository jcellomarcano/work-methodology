# Research A1: role-based agent permissions (S1, S2) · read 2026-10-18

Question: per-agent least privilege bound to scope and folder, a once/timed/session grant outside it, auto and bypass
kept useful. Research only. Tags: [M] Measured (read in code or a fetched page), [I] Inferred, [U] Unknown. Kit paths are `file:line@ecdba23`.

## 1. What the kit enforces today vs prose only

| Piece | Enforced by | Strength | Evidence |
|---|---|---|---|
| Subagent never edits shared build files or `.claude/**` | `guard_paths.py` PreToolUse deny | absolute, any RDD mode | `03-tools/hooks/guard_paths.py:27-31` [M] |
| Owner session editing a build file | hook `ask` | absolute; `.claude/**` in the owner session passes the hook | `guard_paths.py:33-36` [M] |
| Subagent writes inside `may_write` ∪ open receipt `scope_globs` | same hook | only if `rdd.enabled`, default mode `warn` (log only) | `guard_paths.py:38-56`; `03-tools/config/project.json:49`; `_common.py:84-86` [M] |
| Writer role with no receipt | placeholder globs (`<…>`) dropped, empty allowlist returns allow | not enforced | `guard_paths.py:42-47`; `01-roles/agents/generic-proposer.contract.json:23-24` [M] |
| Read scope | no PreToolUse matcher on Read/Grep/Glob | prose only | `03-tools/hooks/hooks.settings.json` PreToolUse matchers [M] |
| Writes through Bash (`sed -i`, `>`, scripts) | nothing: the path guard matches `Edit\|Write\|MultiEdit` | not enforced | `hooks.settings.json`; `guard_gates.py:20-22` "Guardrail, not a sandbox" [M] |
| Delivery (push, PR, merge, tag) and receipt open/close by a subagent | `guard_gates.py` deny | absolute | `guard_gates.py:117-121`; force push `:104-108` [M] |
| Owner delivery without approved receipt | warn, or `ask` in block mode | RDD mode | `guard_gates.py:139-148` [M] |
| Tool-call budget | `budget.py` deny past `max_tool_calls` | absolute (subagents) | `budget.py:37-39` [M] |
| Tool list | harness frontmatter; contract `tools` kept in sync by a test | harness-enforced | `00-principles/agent-protocol.md:49`; `03-tools/tests/test_agents_contracts_sync.py` [M] |
| `may_spawn: []`, `may_talk_to_user: false` | no hook; only by leaving the `Agent` tool out of `tools` | prose (+ tool list) | `agent-protocol.md:47,56`; C4 [M] |
| Network | nothing | prose only | no hook or contract field [M] |
| Post-hoc scope check | `role_contract_validator.py` FAIL on forbidden / outside allowlist | detection, run on demand, not a gate | `03-tools/lib/role_contract_validator.py:92-116` [M] |

Hooks fail open on an exception (`_common.py:215-224`); a missing contract becomes `{}`, so no allowlist
(`guard_paths.py:41`); "subagent" only means `agent_type` or `agent_id` is set (`_common.py:89-90`). The validator
matches allow globs with plain `fnmatch` (`role_contract_validator.py:61-65`) but forbidden ones with the case-folding
`build_files` matcher (`:102`) [I: may disagree]. Net: the absolute set is a hook deny, scope is advisory, read, Bash
writes and network are prose.

## 2. Per harness: permission model, auto mode, bypass

**Claude Code.** Modes `default` (Manual), `acceptEdits`, `plan`, `auto`, `dontAsk`, `bypassPermissions` [C1 M].
Rules are `Tool(specifier)` in `permissions.allow|ask|deny`: "Rules are evaluated in order: deny, then ask, then
allow." [C2 M]. `Edit(path)` / `Read(path)` use gitignore patterns; "`Edit` rules apply to all built-in tools that edit
files." [C2 M]. `--add-dir`, `/add-dir` and `additionalDirectories` widen the working folder [C2 M]. Native grants: once;
"don't ask again" for Bash is saved per repository in `.claude/settings.local.json`, while "A file-modification approval
isn't saved to the file: as the table shows, it lasts until the session ends." [C2 M]. No time-boxed grant [M, absent].
PreToolUse hooks return `allow|deny|ask|defer` and `updatedInput`, which "Replaces the entire input object, so include
unchanged fields alongside modified ones." [C3 M]; but "PreToolUse hook decisions don't bypass permission rules." [C2 M].
Managed settings can lock it: `disableBypassPermissionsMode`, `disableAutoMode`, `allowManagedPermissionRulesOnly`,
`allowManagedHooksOnly`; user `disableAllHooks` cannot turn off managed hooks [C2, C3 M]. Subagents: `tools`,
`disallowedTools`, `permissionMode`; in bypass, acceptEdits or auto "the subagent runs in that same mode and Claude Code
ignores the `permissionMode` you set" [C4 M]; "If you omit `Agent` from the `tools` list entirely, the agent can't spawn
any subagents with the Agent tool." [C4 M].
- Auto: deny rules hold; ask rules and hook `ask` still prompt, "because auto mode still shows you those prompts" [C1 M];
  "On entering auto mode, broad allow rules that grant arbitrary code execution are dropped" [C1 M].
- Bypass: "Deny rules block in every mode, including `bypassPermissions`." and "Allow rules have no effect in
  `bypassPermissions`." [C1 M]. Hooks: PreToolUse runs "for every tool except" `EndConversation` [C2 M] and hook input
  carries `permission_mode: "bypassPermissions"` [C3 M], so hooks run and a hook `deny` holds [I]; a hook `ask` in bypass
  is [U]. In `-p` bypass, calls that would still prompt are denied [C1 M]. `--settings '{"disableAllHooks": true}'`
  turns hooks off for a run [C3 M].
- Sandbox: "The sandbox covers shell commands only." [C5 M]; under bypass the `dangerouslyDisableSandbox` retry "runs
  without a prompt" unless `allowUnsandboxedCommands: false` [C5 M]. Edit/Read denies reach Bash file commands Claude
  Code recognizes, but "They don't apply to a command that reads files without naming them" nor to arbitrary
  subprocesses [C2 M].

**Codex CLI.** Sandbox `read-only | workspace-write | danger-full-access` plus approval `on-request | never | granular`
(`untrusted` retired) [X1 M]. In `workspace-write`, `.git`, `.agents`, `.codex`, `.aws` stay read-only [X1 M]. `--yolo`
(`--dangerously-bypass-approvals-and-sandbox`) means "No sandbox; no approvals" [X1 M]. `auto_review` sends approvals to
a reviewer agent; "Prompt-build, review-session, and parse failures fail closed." [X1 M]. Command rules: "Use rules to
control which commands Codex can run outside the sandbox." with "`forbidden`: Block the request without prompting." [X4
M]; whether they bite under `--yolo` is [U]. Hooks: PreToolUse covers Bash, `apply_patch` (matches Edit/Write) and MCP;
`deny` works, `ask` is "parsed but not supported yet" and the call continues [X2 M]; "Non-managed hooks must be reviewed
and trusted before they run." [X2 M], skippable with `--dangerously-bypass-hook-trust`; input carries `permission_mode`
incl. `bypassPermissions` [X2 M], so hooks run under bypass [I]. Codex itself says "Treat tool hooks as a useful
guardrail, not a complete enforcement boundary." [X2 M]. Subagents inherit sandbox and approvals "including changes made
with `/permissions` or `--yolo`. A custom agent file can't replace those settings." [X3 M]. The kit's `guard_paths.py`
finds no `file_path` in `apply_patch` and allows (`odd/research/harnesses/codex.md:115@ecdba23`) [I].

**OpenCode.** `permission` per tool and per pattern: `allow | ask | deny`, last match wins; per agent, "Agent
permissions are merged with the global config, and agent rules take precedence." [O1 M]. `external_directory` (paths
outside the working folder) and `doom_loop` default to ask [O1 M]. Ask offers `once`, `always` ("for the rest of the
current OpenCode session") and `reject` [O1 M]. `--auto`: "Explicit "deny" rules are still enforced. Auto mode only
changes requests that would otherwise ask for approval." [O1 M]. No separate bypass flag beyond `"permission": "allow"`
and no OS sandbox on the page [I]. "Users can always invoke any subagent directly via the @ autocomplete menu, even if the
agent’s task permissions would deny it." [O2 M]. Bash writes escape `edit` rules (`opencode.md:99@ecdba23`) [I]; a
plugin `tool.execute.before` throw blocks, and whether it runs under `--auto` is [U].

**Antigravity (and Gemini CLI).** One engine of `action(target)` resources (`read_file`, `write_file`, `command`,
`unsandboxed`, `read_url`, `execute_url`, `mcp`); "Conflicting rules are strictly evaluated in priority order: Deny >
Ask > Allow" [A1 M]. Presets: Default (terminal sandbox on, workspace + temp, ask outside), Request Review (always
ask), Turbo (sandbox off, full filesystem, MCP and web allowed); "Your configured allow, deny, and ask rules are layered
on top of the preset and always take precedence" [A1 M], so a deny survives Turbo [I]. A grant edited in the prompt card
"applies the expanded grant for the remainder of the turn" [A1 M]; `write_file` grants feed the sandbox's write list
[A1 M]. CLI rules live only in the global `~/.gemini/antigravity-cli/settings.json` [A1 M]. Headless: "A tool that
requires approval it can’t obtain is soft-denied" and "--dangerously-skip-permissions approves all tool calls, including
file writes and command execution." [A2 M]; whether deny rules hold under that flag is [U]. Hook decisions include
`force_ask` and `deny_unless_prior_grant`: "Denies execution unless the resource was previously approved in a prior
grant." [A3 M]; payload is camelCase, which the kit guards cannot read yet (`antigravity.md` §5) [M]. Gemini CLI: policy
tiers, "Admin policies always override User, Workspace, and Default policies" [G1 M], yet in yolo "mode, a high-priority
rule allows all tools." [G1 M] (which wins is [U]); in an untrusted folder "You will always be prompted before any tool is
run, even if you have auto-acceptance enabled globally." [G2 M].

**pi (gentle-pi).** No hook system; the kit extension runs the same Python hooks on every `tool_call` and blocks on
`deny`, and on `ask` for a subagent or without UI (`metodo-hooks.ts:243-268`) [M]. pi's own modes were not researched [U].

| Layer | Manual | Auto | Bypass / yolo / Turbo |
|---|---|---|---|
| Native deny rules | hold | hold (Claude, OpenCode) [M] | hold in Claude [M], Antigravity [I]; Codex `--yolo`, agy skip [U] |
| Kit hook `deny` | holds while hooks load | holds [I] | holds in Claude, Codex [I]; off with `disableAllHooks` or untrusted hooks |
| Kit hook `ask` | prompts | prompts (Claude) [M] | [U] Claude; Codex never supports it; pi blocks subagents |
| OS sandbox (Bash only) | holds | holds | Claude: unsandboxed retry without prompt; Codex `--yolo`, Turbo: gone |
| Post-hoc validator, receipt diff | detects | detects | detects (mode-independent: reads `git`) |

## 3. Design sketch: role-based permissions [I]

**Capability set per role (RBAC: role → permissions, S4).** One pure function, e.g. `lib/permissions.py
resolve(contract, receipt, brief, grants, now) -> capset`, used by every guard and renderer:
`{read: globs, write: globs, tools: [...], bash: none|readonly|tests|sandboxed, network: off|allowlist,
deliver: false, spawn: [], talk_to_user: false}`. Ceiling = role contract; task scope narrows it, never widens it.
- Write = (`may_write` ∩ task scope) ∪ working folder (round dir, scratchpad, the agent's worktree) ∪ live grants,
  minus the always-forbidden set (build files, `.claude/**`, secrets). Task scope comes from, in order: the open
  receipt's `scope_globs` (`rdd_receipt.py:221`), the change card's "How far", the brief's `scope`.
- Read = repo working folder + `additionalDirectories` by default; outside needs a grant. Reads matter because the
  lethal trifecta is private data + untrusted content + exfiltration (S9) and injection rides on tool data (S6, S7).
- A writer with no scope fails closed (deny), unlike today's empty-allowlist allow (`guard_paths.py:46-47`); OWASP:
  "Fail closed for unknown tools or missing approval requirements." (S2).

**Out-of-scope decision.** Subagent: `deny` with a reason telling it to list the need under `not_covered` (it cannot
answer a prompt; pi already does this, `metodo-hooks.ts:261`). Owner session: `ask`. Delivery stays owner-only.

**Grants in the ledger.** The owner (never an agent) issues a grant through an owner-only MCP tool gated like the receipt
tools (`guard_gates.py:117-121`). Record in `out/hooks/<session>/` (`_common.py:97-98`), following S2: "Bind approval to
the exact action. Include the actor, tool name, target resource, normalized parameters, timestamp, and expiry in the
approval record." Fields: `actor` (agent_type or `owner`), `tool`, `target` glob, `type` once|ttl|session,
`issued_at`, `expires_at`, `session_id`, `reason`, `consumed_at`. Once = consumed atomically on first use; ttl = checked
against `expires_at`; session = `session_id` match. The orchestrator relays a grant to a relaunched subagent, as it
relays Fable approvals (`agent-protocol.md` §9). Time-boxed exists only in the kit: natives offer once/session/permanent
(C2), once/always-session (O1), per turn (A1). The kit never writes permanent allow rules into settings.

**Under auto mode and bypass.** Enforce through layers that do not depend on prompts: (1) render the capset's denies as
native deny rules where they hold in every mode (Claude `Edit(...)`/`Read(...)`, OpenCode `edit`, Antigravity
`write_file`); (2) keep the kit hook `deny` for what rules cannot express (receipt scope, grants, expiry); (3) the OS
sandbox for Bash where available; (4) the post-hoc validator plus receipt as the floor that survives everything but only
detects. A kit `ask` still prompts in Claude auto [M] but is unsure in bypass [U] and unsupported in Codex: subagents
get `deny`, the owner gets `ask` (best effort); the decision is logged either way. Bypass therefore keeps prevention for deny-listed paths and hook denies,
and keeps detection for the rest; S1's "Implement authorization in downstream systems rather than relying on an LLM to
decide if an action is allowed or not." is why the floor is a script on `git`, not a prompt.

**Bash.** The path guard never sees Bash. Options, cheapest first: no Bash for read-only roles (today, except proposer
and verifier); native Edit denies, which reach `sed`, `tee` and redirections [C2]; a kit Bash write-target heuristic
(redirections, `sed -i`, `tee`, `cp`/`mv` targets, `git checkout -- <path>`) that denies a target outside the capset,
labeled guardrail, not sandbox, as `guard_gates.py:20-22` already is; OS sandbox `filesystem.allowWrite` = write globs
(Claude), `workspace-write` (Codex), Default preset (Antigravity); network off. Interpreters (`python -c`, `node`)
stay opaque without a sandbox; the validator catches their writes after the fact.

## 4. Deterministic checks and tests that would prove it

- `resolve()` table tests: contract ∩ scope; placeholder dropped; writer without scope → deny; always-forbidden beats any
  grant; read outside the folder → deny for a subagent, ask for the owner.
- Hook fixtures on stdin (style of `03-tools/tests/test_hooks.py`): out of scope in block mode → `deny`; owner → `ask`;
  `once` grant allows one call then denies; expired `ttl` → deny; session grant from another `session_id` → deny; grant
  issued from a subagent → deny; malformed grant file → deny for writes (no fail-open on this path).
- Bash heuristic fixtures: `sed -i s/a/b/ build.gradle`, `echo x > .claude/x`, `tee`, heredoc body not a write,
  `python -c` → logged as opaque.
- Parity test: native deny rules rendered from a capset agree with the hook on a fixed path list (like the
  `HOOK_MATRIX` test in `test_pi_extension.py`). One matcher for allow and forbid (`build_files`).
- Live probes on a throwaway clone (style of `smoke-loop.sh`): `claude -p --permission-mode bypassPermissions` and
  `auto` with a deny rule and a hook deny on a path → file untouched, ledger line present; same for Codex `--yolo` with
  trusted hooks, `opencode run --auto`, `agy -p --dangerously-skip-permissions`. Each closes one [U] in §2.
- Every round: `role_contract_validator.py --scope-glob …` on the diff; `kit-status` counts denies, grants, expiries.

## 5. Risks and open questions

Risks [I]: prompt injection makes an agent ask for grants, so grant prompts become a social-engineering surface and
cause approval fatigue; hooks fail open on any error (`_common.py:215-224`); a user `disableAllHooks` or an untrusted
Codex hook silently removes the hook layer; bypass removes the Bash sandbox; harness rule syntaxes drift (globs differ,
`opencode.md` §2.4); Claude "don't ask again" writes permanent rules the kit does not see; time-boxed grants rely on a
stable `session_id` and clock; subagents inherit the parent mode, so per-role `permissionMode` is not a control.

Open questions for the owner:
1. Writer with no scope (proposer, no receipt): deny (fail closed) or keep today's allow?
2. Fence reads to the working folder, or leave reads open and fence only writes?
3. Grant types once / TTL / session: enough? Default TTL? Owner-only issuer?
4. Under bypass, should a kit `ask` become `deny` (safe, blocks flow) or `allow` plus a ledger line (keeps bypass useful)?
5. May the kit render native deny rules into `.claude/settings.local.json` (it already merges hooks there), or hooks only?
6. Bash: heuristic hook plus OS sandbox, or remove Bash from more roles?
7. Network off by default for every subagent? 8. Move `rdd.mode` for `guard_paths` from `warn` to `block`?

## 6. Sources (read 2026-10-18; HTTP from `curl -sL -w '%{http_code}'`; copies in `$TMPDIR/a1perm`)

| ID | URL | HTTP |
|---|---|---|
| C1-C5 | https://code.claude.com/docs/en/{permission-modes, permissions, hooks, sub-agents, sandboxing}.md in that order | 200 each |
| X1-X4 | https://learn.chatgpt.com/docs/{agent-approvals-security, hooks, agent-configuration/subagents, agent-configuration/rules}.md | 200 each |
| O1, O2; A1-A3 | https://opencode.ai/docs/{permissions, agents}/; https://antigravity.google/docs/{permissions, cli/headless, hooks}/ | 200 each |
| G1, G2 | https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/reference/policy-engine.md, …/docs/cli/trusted-folders.md | 200 each |
| S1, S2 | https://genai.owasp.org/llmrisk/llm062025-excessive-agency/, https://raw.githubusercontent.com/OWASP/CheatSheetSeries/master/cheatsheets/AI_Agent_Security_Cheat_Sheet.md | 200 each |
| S3, S4, S5 | https://csrc.nist.gov/glossary/term/least_privilege, https://csrc.nist.gov/projects/role-based-access-control, https://www.cs.virginia.edu/~evans/cs551/saltzer/ (Saltzer & Schroeder 1975) | 200 each |
| S6-S9 | https://arxiv.org/abs/2302.12173, https://arxiv.org/abs/2406.13352, https://arxiv.org/abs/2503.18813, https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/ | 200 each |

Background quotes: least privilege, "each entity is granted the minimum system resources and authorizations that the
entity needs to perform its function." (S3); RBAC, "Each user is assigned one or more roles, and each role is assigned one
or more privileges that are permitted to users in that role." (S4); "Every program and every user of the system should
operate using the least set of privileges necessary to complete the job." (S5); excessive agency's root cause is
"excessive functionality; excessive permissions; excessive autonomy." (S1); "LLM-Integrated Applications blur the line
between data and instructions." (S6); "data returned by external tools hijacks the agent to execute malicious tasks."
(S7); CaMeL: "the untrusted data retrieved by the LLM can never impact the program flow." (S8). Also fetched, not
cited (200 each): Claude `iam.md`, `settings.md`, `security.md`; Codex `permission-modes.md`; Gemini CLI `sandbox.md`;
OWASP Agentic Top 10 2026. Quote check: 47 of 47 quotes (≥ 20 chars) found, normalized, in the copies or `guard_gates.py`.
