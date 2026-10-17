# Routing by kind of intelligence and budgets

Data that motivated this in the origin project: 88% of spend in sessions with many subagents, 47% in
general-purpose agents, 87% with context over 150k. The question isn't "which model is cheap" but "what
kind of intelligence does this task need?".

| If the task… | Goes to | Kit role | Context cap |
|---|---|---|---|
| is solved by a rule | script (`03-tools`) | | 0 |
| is solved by AST or static analysis | pinned CLI tool (detekt, PMD CPD, ktlint…) | | 0 |
| is a behavior rule (gate, budget, output shape) | deterministic hook (`03-tools/hooks/`) | | 0 |
| interprets a measured result against a fixed rulebook | small model | `generic-style-reviewer`, `generic-mechanic`, `generic-comment-gate` | 15k |
| needs technical reasoning | medium model | `generic-cartographer` 40k, `generic-proposer` 60k, `generic-verifier` 40k, `generic-boundary-reviewer` 40k, `generic-judge` 30k | 30-60k |
| needs adversarial judgment or touches the irreversible | large model | `generic-challenger`, `generic-blind-spot-adversary`; the judge escalates here on a P0 or a critical property | 60k |
| is a high-impact decision | the owner | | |

## Rules

- Never a general-purpose agent: each role is an agent with `model`, minimal `tools`, a place in the
  loop, and a JSON contract (`forbidden_paths`, `may_spawn: []`, `max_context_tokens`). If a role doesn't
  exist yet, use a generic agent with an explicit `model` and a template brief, and the minutes declare
  it.
- An agent returns JSON or a table, never dumps. Exceeding its cap is a protocol finding.
- **Adversary cost gate**: adversaries go to the large model when `For what` or `What it risks` is one of
  the project's critical properties, or when the diff touches the declared critical paths; only when both
  fields are cosmetic and the diff doesn't touch the critical path does the medium model review. The path
  outranks the declaration: `change_card_validator.py` returns the lane, not the prose.
- **Budget per change**, declared in the card: a change that doesn't touch the critical path closes with
  a proposer and a medium-model reviewer; the cartographer is reused if the map is under a week old.
- **Orchestration**: the medium model orchestrates the routine skills in short, separate sessions; the
  highest-judgment model designs, decides, and talks to the owner.
- **Context hygiene**: compact when closing each block, clean up when switching tasks; the session log
  measures tokens per phase and per agent and feeds the process benchmark.
- Escalate after two stalls, don't push through; a critical finding from a small model gets verified above
  before it's taken as good. Cheap fan-out, expensive funnel.

## Cost measured in the origin project (for calibration, not to copy)

Full-repo cartographers: 135k-182k tokens each. Large adversaries: 106k-146k with a 60k cap.
An L-sized implementation train: 562k tokens and 268 calls (nine times its cap): large assignments split
into units with their own STOP. Cartography runs scoped to one module with a small model: 26k-30k,
dominated by file reading, not by the brief.

## Other providers

The tiers above are kinds of intelligence, not brands. Which Google or OpenAI models can occupy each
tier, with what harness and after what admission test, lives in `multi-provider-routing.md` and in
`03-tools/config/model-tiers.json`. No model enters a role without that document's admission test.
