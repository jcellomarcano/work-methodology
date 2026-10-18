# Context pack · read this first (≤ 120 lines)

You are entering a project that works under this methodology. Linked material waits until a task needs it.

## 1. What we optimize

We do not optimize code: we optimize **system properties**. Every project declares its hierarchy of
what is protected, in tie-break order (e.g. a bookings service: capacity, booking state, request
identity, integrity, security, UX). Speed yields to the properties above it. **Simplicity before
over-engineering**: the simplest solution that satisfies the invariants wins; a new abstraction earns
its cost only with a second real reason to change. The central question: how do systems keep evolving
without losing what makes them correct?

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
- **Benchmark per release.** No merge to the release branch without a benchmark against the last
  shipped tag, including what was NOT measured.
- **Real-environment measurement**: one primary metric per single-variable arm, medians, negative control.

## 3. How work is routed (`model-routing.md`)

| If the task… | Goes to | Cap |
|---|---|---|
| is solved by a rule | script | 0 |
| is solved by AST or static analysis | pinned CLI tool | 0 |
| interprets a measured result against a fixed rulebook | small model (style reviewer, mechanic) | 15k |
| needs technical reasoning | medium model (cartographer, proposer, verifier, boundary reviewer) | 40-60k |
| needs adversarial judgment or touches the irreversible | large model (challenger, blind spots, judge) | 60k |
| is a high-impact decision | the owner | |

Never a general-purpose agent: each role has a model, minimal tools and a JSON contract; `bin/route.sh`
picks model and effort per launch. Exceeding the cap is a protocol finding, not an agent failure.

## 4. How agents are briefed and how they answer (`agent-protocol.md`)

Fixed-template brief in terse English: `ROLE · OBJECTIVE · INPUTS (paths) · CONSTRAINTS · OUTPUT
(schema) · STOP · BUDGET · EVIDENCE`. Handoff via a numbered file; the script sets the sha. With the
owner, use their language. The installers append this core, byte for byte, to every kit agent:

<!-- subagent-core:start -->
- The kit: a working method for AI-built software. Scripts measure; in each round's loop (cartographer,
  proposer, comment gate, challenger with blind-spot adversary, judge, verifier, style and boundary
  reviewers, mechanic) role agents map, build, attack, rule and verify one change card; the owner decides.
- Evidence or silence: cite the code statement at `file:line`, never a comment; tag every claim
  Measured, Tested, Inferred, Assumed or Unknown.
- Answer JSON only, with `mcp__metodo__output_write` and your role's schema; a FAIL writes nothing,
  so fix and retry. Zero findings is valid. Never reword the brief.
- Whenever you stop before your STOP condition (budget deny, context or tool limit), emit your JSON
  with `truncated: true` and `not_covered`.
- Never edit shared build files or `.claude/**`, with any tool, Bash included.
- Push, PR, merge, tags, external tickets, receipt start/finalize/acknowledge: the owner's; report
  them, never run them. Never talk to the owner; never spawn agents.
<!-- subagent-core:end -->

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

Run `03-tools/bin/init.sh <repo>` (or the `init-kit` skill, which interviews the owner and calls
it): instance, adaptation, scaffolds, pinned tools, install, first baseline and map, then the wiring
doctor (`bin/doctor.sh`) and the full-loop smoke (`bin/smoke-loop.sh`). Its report lists what is left
to you, by `05-adopt/checklist.md` section: the property hierarchy, the invariants with their
guarantee mechanism, boundary nodes and doc caps, owner and gates. Only then open the first change card.
