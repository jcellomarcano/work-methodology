# Adoption

How to bring this methodology into a new or existing project.

## Step checklist

- [ ] Declare your protected properties ranking ([docs/01-principles.md](01-principles.md))
- [ ] Write invariants and their guard mechanisms
- [ ] List critical paths (the ones that trigger the High review tier)
- [ ] Pick or confirm risk-tier rules for your project
- [ ] Define owner gates and an emergency lane
- [ ] Copy `04-templates/` into your project
- [ ] Run one real change through the full loop as a pilot
- [ ] Retro after 2 weeks: what worked, what felt heavy, what to adjust

Record all of this in your project's copy of [04-templates/project-profile.md](../04-templates/project-profile.md).

## Minimum viable adoption vs. full adoption

| | Minimum viable | Full |
|---|---|---|
| Evidence or silence | Yes | Yes |
| Change card | Yes | Yes |
| Small, green commits | Yes | Yes |
| Risk-tiered review | Yes | Yes |
| Feature task documents | No | Yes |
| Benchmarked releases | No | Yes |
| Emergency lane, cadence rituals | No | Yes |

Start minimum viable if the team is new to this. Move to full adoption once the habits stick — usually after the pilot and its retro.

## Using AI agents (optional)

AI agents are optional helpers. They never own a decision gate — a human owner always does. Route work to the right kind of intelligence instead of using one large model for everything:

| Kind of work | Route to |
|---|---|
| A fixed rule | A script |
| Static analysis | A pinned analysis tool |
| Interpretation against fixed rules | A small model |
| Technical reasoning | A medium model |
| Adversarial judgment or irreversible actions | A large model |
| High-impact decision | A human owner |

If it's deterministic, it should be a script: same input hash should produce the same output.

### Agent brief

Every agent gets a narrow role, minimal tools, and a fixed brief. Use [04-templates/agent-brief.md](../04-templates/agent-brief.md):

- **ROLE** — the one thing this agent does
- **OBJECTIVE** — what "done" looks like
- **INPUTS** — exactly what it's given
- **CONSTRAINTS** — what it must not do
- **OUTPUT schema** — the structured shape of its answer
- **STOP condition** — when it must stop and hand back
- **BUDGET** — time/token/step limit
- **EVIDENCE** — what proof it must attach to its output

Agents return structured output. They never decide gates — a human reads the output and decides.
