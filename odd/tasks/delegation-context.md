# Feature: delegation-context

**Objective.** Make delegation deterministic (who works: the main coordinator or a subagent, foreground or background) and implement the context method (`odd/research/context/context-method.md` §9 WU5-WU17) with the owner decisions D1-D12 already taken.
**Branch.** `feat/delegation-context` from published main a22062b, worktree `~/metodologia-de-trabajo-worktrees/model-router`. One commit per task, test-first where behavior changes, README status block re-measured in the same commit (`03-tools/bin/kit-status.sh --write`), privacy scan before any push.
**Context.** WU1-WU4 are already done and published (agent dedupe, subagent core, token caps, AGENTS trim). Decisions D1-D12: `odd/tasks/context-optimization.md` L6.

## Specs

Quoted fragments are the user's exact words (Spanish, 2026-10-18); the requirement text is English.

- **S1 Who decides delegation.** "quien se encarga de decidir cuando toca usar multiagente en background y ciando no? es util manejar un agente que sea el chat con el ususario y que sea el coordinador y los demas tareas las hagan multiagentes por debajo o no, proque a veces me pasa que lanzo la metodologia, peor el agente que lo hace es el main one". The main agent is always the coordinator and the voice to the owner; the router decides deterministically, per role, whether the work runs in a subagent or in the main session and whether in background or foreground; review roles (challenger, blind-spot adversary, judge, verifier) always run as subagents.
- **S2 Main session cannot silently do the team's work.** At medium and high tiers a main-session source edit outside a small task gets a visible warning naming the proposer, and a review whose author is the main session invalidates the receipt.
- **S3 Delegation is measured.** The benchmark measures the share of steps the main session delegated against what the router asked.
- **S4 Context method.** Implement WU5-WU17 of `context-method.md` §9 with decisions D1-D12.
- **S5 Task list and saved context.** "si, crea una tarea con la lista de cosas pro hacer, guarda el contexto encesario y compacta la memoria, luego de eso empeizas". This document is the list; its Engram mirror and a compact session summary hold the context.

## Tasks (smallest first)

| ID | Specs | Work | Status | Evidence |
|---|---|---|---|---|
| T1 | S4 | WU6: reply_lint Stop hook OFF (D3), skill `human-reply` stays; Claude settings + pi HOOK_MATRIX | done | RED 3F/1E → GREEN 95 OK (settings_merge, hooks, pi extension, doctor); re-install sweeps kit entries under events the kit no longer ships |
| T2 | S4 | WU5: visible WARN channel (warn reaches the agent: `additionalContext` / `systemMessage`), one emit helper in `_common.py` | todo | |
| T3 | S4 | WU7: compaction restore on SessionStart(compact) — task doc, open S#, last receipt — and orchestrator window 300k (D1) | todo | |
| T4 | S4 | WU10: subagent report cap 2,000 tokens (D9), verdict per S# in reports, `max_context_tokens` checked on close | todo | |
| T5 | S4 | WU11: goal contract in the brief (objective, S# by reference, acceptance, scope, STOP, budget, already read), `omitClaudeMd` for contract roles (D10) | todo | |
| T6 | S1 | Router delegation decision: per roster entry `delegate: subagent|main` and `background: true|false`, from tier, task kind, modules, read size, independence; review roles always subagent | todo | |
| T7 | S2 | Main-session guard: visible warn on main-session source edits at medium/high outside small tasks; receipt invalid when a review capture's author is the main session | todo | |
| T8 | S4 | WU14: `activation.py` profiles (bare/light/scripts/standard/full), `hook_mode` from the profile, router profile cap | todo | |
| T9 | S4 | WU9: hook run counters, latency, per-element verdicts and expiry (D11 thresholds) | todo | |
| T10 | S3, S4 | WU8: transcript metrics (per-role peak vs cap, tool-output share, re-read ratio, report size, startup load, recall-used, delegation ratio vs router) | todo | |
| T11 | S4 | WU12: tool-output filter hook (full output to a file, summary to context) | todo | |
| T12 | S4 | WU13: Engram read rule (D4: main session only, start/resume, byte cap, kill switch) | todo | |
| T13 | S4 | WU15-16: `run-check.sh` + `runs.jsonl`; `done_check.py` with DONE-01..17, CLI and MCP tool | todo | |
| T14 | S4 | WU17: done-gate Stop hook warn-first (D2), owner waiver, skill steps, COM-20 | todo | |
| T15 | S1-S4 | Code review (two blind reviewers) + independent verifier, re-measure, privacy scan, push | todo | |

## Log

- **L1** (user, 2026-10-18, verbatim): see S1. Answer given: no deterministic owner today; the main agent decides from prose; the PR 176 pilot measured the kit arm running with no subagent (methodology-benchmark L13).
- **L2** (user, 2026-10-18, verbatim): see S5. Document created, Engram mirror `odd/delegation-context/tasks`, compact session summary saved; work starts at T1.
