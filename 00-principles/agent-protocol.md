# Protocol between agents · v1

With the owner, speak their language. Between agents, this applies. Schemas in `03-tools/schemas/`.

## 1. Brief shape: the goal contract, a fixed template in terse English

Goal contract (`04-templates/brief.md`), fields in order: `ROLE` (one specialised role, never
general-purpose) · `OBJECTIVE` (one verifiable sentence) · `SPECS` (`<task-doc>.md#S<n>` references, never
paraphrased, or `none`) · `ACCEPTANCE` (the proving check; with `OBJECTIVE`, the goal) · `INPUTS` (paths)
· `SCOPE` · `ALREADY READ` (paths the parent read, or `none`) · `CONSTRAINTS` · `OUTPUT` · `STOP` ·
`BUDGET` (roster `max_context_tokens`, else the contract's; `max_tool_calls`) · `EVIDENCE` (§3).
`lib/brief_check.py` fails a missing, empty or misplaced field, a general-purpose role, a multi-sentence
objective, prose in `INPUTS`, a paraphrased S#, a numberless BUDGET and a brief over 60 lines. Measured:
fixed template 9.0/10 vs 5.5 prose, 7.0 JSON, fewer tokens and calls; JSON is for OUTPUT only.

## 2. Output shape: JSON against a schema, with a tag per claim

Always valid JSON per the declared schema, no fences or surrounding prose. Every claim carries
`epistemic`: `Measured | Tested | Inferred | Assumed | Unknown`. Zero findings is a legitimate output. An
agent returns verdicts and tables, never file dumps. Out of budget, the output carries `truncated: true`
and `not_covered`; a truncated round is never read as clean; the orchestrator may relaunch it narrower.

## 3. Evidence rule: the statement, not the comment

Every claim about code cites `file:line` (with the sha) of the statement that proves it: signature,
`var`, loop, call with a side effect. Never a comment or KDoc. Measured: five of six runs called an
imperative machine pure because its KDoc said "pure". The verifier checks this point first. Source
citations are copied literally in their original language, never translated.

## 4. Handoff via a numbered file, with a sha set by script

An agent never writes to another: it leaves `NNN-<role>-<subject>.json` in the round's directory with
`output_write` (validated against its schema) and hands off with `handoff_write` or `receipt_capture
--handoff-to`; the script sets the sha (`lib/handoff.py`), never typed by hand. A change to the proposal
invalidates the previous self-challenge: the receipt applies it (new tree, new receipt).

## 5. Cold-start context pack

Fixed size: the subagent core + the module map (paths and LOC, not content) + the role's contract +
pointers to the project's conventions; never the whole repo. The core is the `CONTEXT-PACK.md` section
between `<!-- subagent-core:start -->` and `<!-- subagent-core:end -->`; `lib/render_agents.py` appends it
byte for byte to every installed agent (on pi, before the contract and role marker), so no body copies it.
The rest is read on demand inside `SCOPE`; savings live there and in `STOP`: file reading dominates cost.

## 6. Role contract (machine-readable)

`<agent>.contract.json`: `model`, `tools`, `forbidden_paths` (always the shared build files and
`**/.claude/**`), `may_write` (empty except for the proposer and mechanic, extended at runtime by the
skill with `--scope-glob`), `may_spawn: []`, `may_talk_to_user: false`, `handoff_targets`,
`max_context_tokens`, `max_tool_calls`. Validated by `role_contract_validator.py` against `git diff
--name-only`; `tools` is enforced by the frontmatter (MCP tools instead of Bash except for the proposer
and verifier) and a test keeps them in sync; `max_tool_calls` feeds the budget hook and `maxTurns`.

## 7. Prohibitions

No launch without a goal contract (`mcp__metodo__brief_check`, then the `guard_spawn` hook on the launch).
No dumping files into the brief, no rewording it. An adversary never proposes the fix. No agent spawns
subagents without explicit `may_spawn` (same hook). No agent talks to the owner: the orchestrator does. No
claiming "deterministic" without the exact command per criterion. No worker writes memory: it reads only
the `engram:` references in its `INPUTS`; the orchestrator saves (`runtime-adapters.md` §5).

## 8. Measurement

Per run, log tokens, calls, rounds to verdict, first-pass acceptance, and errors caught by the verifier.
Without these figures, no protocol change gets defended.

## 9. Routing: the orchestrator calls the router, the owner approves

Before launching any role, the orchestrator (or the skill it runs) calls `route` and launches exactly the
roster it returns, with its model and effort; frontmatter `model:` is only the fallback when the router is
down. No agent calls the router. A `requires_approval` entry (Fable 5.1) launches only after the owner's
explicit OK, relayed by the orchestrator as `approvals`; the rule id goes in the round context.

## 10. Comments in code (DOC-001)

The proposer doesn't write comments: if it thinks one's needed, it leaves
`// NEEDS-COMMENT: <reason>` on the line before the statement. `comment_gate.py` lists and measures the
diff's new comments; `generic-comment-gate` (small model) rules NECESSARY, UNNECESSARY,
MAKE-SELF-EXPLANATORY, or KDOC-INTERFACE and proposes the text; the mechanic applies it;
`comment_gate.py --verify` proves only comments changed and no marker remains.
