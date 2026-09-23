# Change card

Every defense of a change uses this card, with the nine fields in this order, one line per field. Each
field ends with its epistemic tag in brackets: `[Measured]` `[Tested]` `[Inferred]` `[Assumed]`
`[Unknown]`. If a field can't be filled in, write `inconclusive` and don't defend the change: investigate
it instead. Validated by `03-tools/lib/change_card_validator.py`, which also returns the review lane.

| Field | What it answers | Accepted answer |
|---|---|---|
| **Why** | the cause that triggers it | evidence: file:line with sha, log, measurement |
| **For what** | the property it improves | one from the project's hierarchy (`config/project.json`) |
| **What it risks** | the property that may worsen | one from the same list, or `none` with its proof |
| **When** | what makes it necessary now | a concrete trigger, never "because it's convenient" |
| **How** | the mechanism | one sentence, no adjectives |
| **How far** | the limit | what it does NOT do, what stays ticketed, and how it's undone if it goes wrong |
| **How we'll know** | the verification | test, guard, script, or real-environment minutes |
| **Invariant** | what must stay true | project `INV-xx`; mandatory if `For what` or `What it risks` is a critical property; otherwise `n/a` |
| **Ticket** | traceability | the ticket tracker's key, or an explicit `no ticket` |

The change's budget (agents and tokens) is declared alongside the card; the session log measures it.

## Template

```markdown
## Change card
**Why**: Store.kt:73-78 @ a1b2c3d declares the obligation lives only in memory [Measured]
**For what**: Recoverability [Measured]
**What it risks**: UX, one extra write before the external call [Assumed]
**When**: before the feature's first real deployment [Inferred]
**How**: write-ahead log of the terms before the external call and reconcile() on startup [Inferred]
**How far**: doesn't touch legacy providers; undone by reverting the commit and deleting the log [Measured]
**How we'll know**: process-death test across the three windows; real-environment minutes [Tested]
**Invariant**: INV-04
**Ticket**: no ticket
```

Note: `03-tools/lib/change_card_validator.py` matches these exact English field labels (`Why`, `For
what`, `What it risks`…) and the epistemic tags literally (`Medido`, `Probado`, `Inferido`, `Asumido`,
`Desconocido` — kept as-is; see `03-tools/config/change-card.template.md`).
