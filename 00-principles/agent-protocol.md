# Protocol between agents · v1

With the owner, speak their language. Between agents, this applies. Schemas in `03-tools/schemas/`.

## 1. Brief shape: fixed template, in terse English

Mandatory fields, in this order: `ROLE` · `OBJECTIVE` (one verifiable sentence) · `INPUTS` (paths, never
pasted content) · `CONSTRAINTS` (what's untouched, reading scope) · `OUTPUT` (schema reference) ·
`STOP` (when to stop and return) · `BUDGET` (tokens and tools) · `EVIDENCE` (the evidence rule, §3).
Measured in the origin project: the fixed template scored 9.0/10 against 5.5 for free prose and 7.0 for
JSON, with fewer tokens and fewer calls. JSON with a schema is reserved for OUTPUT, not for the brief.

## 2. Output shape: JSON against a schema, with a tag per claim

Always valid JSON per the declared schema, no fences or surrounding prose. Every claim carries
`epistemic` with one of `Measured | Tested | Inferred | Assumed | Unknown`. Zero findings is a legitimate
output. An agent returns verdicts and tables, never file dumps. If it runs out of budget before finishing,
the output carries `truncated: true` and `not_covered`; a truncated round is never read as clean and the
orchestrator decides whether to relaunch it with less scope.

## 3. Evidence rule: the statement, not the comment

Every claim about code cites `file:line` (with the sha) of the statement that proves it: signature,
`var`, loop, call with a side effect. Never a comment or KDoc. Measured: five of six runs called an
imperative machine pure because its KDoc said "pure". The verifier checks this point first. Source
citations are copied literally in their original language, never translated.

## 4. Handoff via a numbered file, with a sha set by script

An agent never writes to another: it leaves `NNN-<role>-<subject>.json` in the round's directory with
`output_write` (validated against its schema) and hands off with `handoff_write` or
`receipt_capture --handoff-to`; the script sets the sha (`lib/handoff.py`), the agent never types a sha
by hand. A change to the proposal invalidates the previous self-challenge: the receipt applies it (new
tree, new receipt).

## 5. Cold-start context pack

Fixed size: the kit's `CONTEXT-PACK.md` + the module map (paths and LOC, not content) + the role's
contract + pointers to the project's conventions. Never the whole repo. The rest is read on demand within
the brief's `scope`. Cost is dominated by file reading, not by the brief: the savings live in `scope` and
`STOP`.

## 6. Role contract (machine-readable)

`<agent>.contract.json`: `model`, `tools`, `forbidden_paths` (always the project's shared build files and
`**/.claude/**`), `may_write` (empty except for the proposer and mechanic, extended at runtime by the
skill with `--scope-glob`), `may_spawn: []`, `may_talk_to_user: false`, `handoff_targets`,
`max_context_tokens`, `max_tool_calls`. Validated by `role_contract_validator.py` against
`git diff --name-only`; `tools` is enforced by the agent's frontmatter (MCP tools instead of Bash except
for the proposer and verifier) and a test keeps them in sync; `max_tool_calls` feeds the budget hook and
`maxTurns`. Exceeding the cap is a protocol finding, not an agent failure.

## 7. Prohibitions

No dumping files into the brief. No rewording the brief before executing. An adversary never proposes the
fix. No agent spawns subagents without explicit `may_spawn`. No agent talks to the owner: that's the
orchestrator's job. No claiming "deterministic" without the exact command per criterion.

## 8. Measurement

Per run, log tokens, calls, rounds to verdict, first-pass acceptance, and errors caught by the verifier.
Without these figures, no protocol change gets defended.

## 9. Comments in code (DOC-001)

The proposer doesn't write comments: if it thinks one's needed, it leaves
`// NEEDS-COMMENT: <reason>` on the line before the statement. `comment_gate.py` lists and measures the
diff's new comments; `generic-comment-gate` (small model) rules NECESSARY, UNNECESSARY,
MAKE-SELF-EXPLANATORY, or KDOC-INTERFACE and proposes the text; the mechanic applies it;
`comment_gate.py --verify` proves only comments changed and no marker remains.
