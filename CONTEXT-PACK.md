# Context pack · read this first (≤ 120 lines)

You are an agent entering a project that works under this methodology. This file gives you the full
context in five minutes. The long material is linked; do not read it until a task calls for it.

## 1. What we optimize

We do not optimize code: we optimize **system properties**. Every project declares its hierarchy of
what is protected, in tie-break order (example from the origin project, a payments app: money, payment
state, transaction identity, integrity, auditability, recoverability, security, UX). Speed yields to the
properties above it. **Simplicity before over-engineering**: the simplest solution that satisfies the
invariants wins; a new abstraction earns its cost only with a second real reason to change. The central
question: how do we build systems that keep evolving without losing what makes them correct? Today's
code is tomorrow's legacy.

## 2. The rules that govern (summary of `00-principles/methodology.md`)

- **Evidence or silence.** No claim without `file:line` (with the sha it was read at), a commit sha, a
  log timestamp, or pasted command output. What isn't proven is called "inconclusive" with the path to
  proving it. Every claim carries a tag: **Measured · Tested · Inferred · Assumed · Unknown**.
  A tag drops when its evidence dies; it never rises without new evidence.
- **Six questions before implementing**: why this exists; what must stay true; what we protect and
  what we risk; where the truth lives; what we assume and how we know it; whether we're making the
  system simpler or just the code shorter.
- **Every defense of a change is a 9-field change card** (`change-card.md`): why, for what, what it
  risks, when, how, how far (including how it's undone), how we'll know, invariant, ticket.
  No card, no PR. A script validates it.
- **Cartographer before surgery.** Before touching non-trivial code, a deterministic map (script) plus
  an agent's reading: what exists, what gets reused, what conflicts will arise.
- **Every commit green on its own** (gstack). The project's battery passes on every commit, not just at
  the end. A push with `--no-verify` is declared in the PR.
- **Round of two adversaries before pushing**: the challenger attacks what is claimed (OK / NUANCE /
  BROKEN) and the blind-spot adversary looks for what nobody is watching (CLOSED / OPEN WITH OWNER /
  CONTAINED). A BROKEN gets fixed before the push; an OPEN needs an owner; OPEN outranks OK until a
  judge rules. The facts they attack with come from scripts; mandatory lenses: simplicity, critical flow
  ("can something irreversible be lost or duplicated?"), "never worse than before".
- **The owner decides at explicit gates**: deployments, PRs, pushes, merges, shared build files,
  external tickets, any shared state. If an instruction rests on a false premise supplied by the agent,
  it stops and gets corrected before executing.
- **New code follows the style; old code only under its own ticket.** DRY of knowledge, not of
  keystrokes. A third-party SDK defect is reported with evidence; an unavoidable patch is born tagged
  with its retirement condition.
- **Determinism by script.** Everything that can be a script is a script, outside the repo, with
  ordered JSON output, no timestamps, `tool_sha` and `repo_sha`, baseline per sha and delta. Same sha,
  same output. Every script ships with a negative control and a determinism test. Skills wrap scripts;
  the model interprets, never re-derives numbers.
- **Benchmark per release.** No merge to the release branch without a benchmark (what improves, what
  worsens, why, how, what was NOT measured), based on the last shipped tag. What's internal to the PR
  goes inside `<!-- -->`.
- **Measurement in a real environment**: one primary metric per arm, single-variable arms, medians,
  negative control, declared observer effect, declared simulations.

## 3. How work is routed (`model-routing.md`)

| If the task… | Goes to | Cap |
|---|---|---|
| is solved by a rule | script | 0 |
| is solved by AST or static analysis | pinned CLI tool | 0 |
| interprets a measured result against a fixed rulebook | small model (style reviewer, mechanic) | 15k |
| needs technical reasoning | medium model (cartographer, proposer, verifier, boundary reviewer) | 40-60k |
| needs adversarial judgment or touches the irreversible | large model (challenger, blind spots, judge) | 60k |
| is a high-impact decision | the owner | |

Never a general-purpose agent: each role is an agent with `model`, minimal `tools`, a JSON contract
(`forbidden_paths`, `may_write`, `may_spawn: []`, `max_context_tokens`). An agent returns JSON or a
table, never dumps. A medium model orchestrates the routine work; the highest-judgment model designs,
decides, and talks to the owner. Exceeding the cap is a protocol finding, not an agent failure.

## 4. How agents are briefed and how they answer (`agent-protocol.md`)

Fixed-template brief in terse English: `ROLE · OBJECTIVE · INPUTS (paths) · CONSTRAINTS · OUTPUT
(schema) · STOP · BUDGET · EVIDENCE`. You answer JSON against the schema, with an epistemic tag per
claim and `truncated`/`not_covered` if you exhaust the cap. You cite the code **statement**, never a
comment (measured: 5 of 6 agents called an imperative machine pure because its KDoc said so).
Handoff via a numbered file; the script sets the sha. You do not reword the brief, you do not spawn
subagents without `may_spawn`, you do not talk to the owner: that's the orchestrator's job. With the
owner, use their language.

## 5. The full loop

cartographer → proposer (one card, no comments) → comment gate (DOC-001) → {challenger, blind
spots} in parallel → judge (with a round cap) → verifier in a clean context → {style reviewer, boundary
reviewer} → mechanic for trivial approved fixes → gate over the mechanic's diff. Each step leaves its
file in the round's directory (`round/000-context.md` first, template in `04-templates/`) and its
minutes.

The loop opens with a **receipt** (`receipt_start`, skill `receipt-review`) tied to the candidate's
tree, with the layer frozen: exempt (nothing), low (scripts only), medium (one challenger with one lens
+ sectors), high (the full round, with the owner's consent). `receipt_finalize` closes from the
captures; approval never pushes or opens a PR. Scripts are called as MCP tools (`mcp__metodo__*`) and
hooks enforce the gates.

## 6. If you're instantiating this in a project

`05-adopt/checklist.md`: declare the property hierarchy, write the invariants with their guarantee
mechanism, configure boundary nodes and doc caps, pin tools, install agents and skills, take the first
baseline, and only then open the first change card.
