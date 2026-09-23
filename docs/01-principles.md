# Principles

These are the ideas everything else in this methodology is built on.

## Evidence or silence

Every claim about the system is backed by evidence, or it's marked "inconclusive."

Acceptable evidence:

- A file and line, tied to a commit (`path/to/file.ts:42@abc1234`).
- A commit SHA.
- A timestamped log line.
- Pasted output from a command you actually ran.

If you can't point to one of these, say "inconclusive" and state how to prove it (e.g. "run the load test with X load to confirm").

## Confidence tags

Tag claims with how sure you are. A tag can only drop when its evidence stops holding — it never rises without new evidence.

| Tag | Meaning |
|---|---|
| Measured | Observed directly (a metric, a benchmark, a log) |
| Tested | Covered by a passing, specific test |
| Inferred | Reasoned from related evidence, not observed directly |
| Assumed | Believed true, not yet checked |
| Unknown | No evidence either way |

## Optimize system properties, not code

Code is a means. What the system protects is the point.

Each project keeps a **ranked list of protected properties** in its `project-profile.md` (see [templates/project-profile.md](../templates/project-profile.md)). A neutral example:

1. Data integrity
2. Correctness
3. Security
4. Recoverability
5. Performance
6. User experience

When two good options conflict, the higher-ranked property wins. This turns "which is better?" into a decision anyone can reconstruct.

## Simplicity first

- The simplest solution that satisfies the invariants wins.
- A new abstraction needs a second real reason beyond "it might be useful later."
- Port, don't redesign, unless the change card says otherwise.
- No speculative flags or configuration for hypothetical futures.
- State explicitly what you are **not** building, so nobody assumes it's coming.

## The six questions before implementing

Answer these before writing code. They belong in the change card (see [docs/03-change-card.md](03-change-card.md)).

1. Why does this exist?
2. What must stay true (invariants)?
3. What do we protect, and what do we risk?
4. Where does the truth live (source of record)?
5. What do we assume, and how do we know?
6. Are we making the system simpler, or just the code shorter?

## Lessons as short rules

- A generated file is not proof. Proof is the command output that produced it.
- Silence is not data. A tool that couldn't see something must say so, not stay quiet.
- Cite the code statement itself, not a comment describing it — comments drift.
- Report results as they are, including your own mistakes. A corrected error is more trustworthy than a hidden one.
