# The why layer: the questions that govern

## 1. Thesis

We do not optimize code: we optimize system properties. The central question is how to build systems
that keep evolving without losing what makes them correct. Today's code is tomorrow's legacy: legacy is
simply the code someone will have to understand after us.

**Simplicity before over-engineering.** Nothing has to be abstract or complex on principle. The simplest
solution that satisfies the invariants is the best one; a new abstraction earns its cost only with a
second real reason to change, never a hypothetical one.

## 2. The hierarchy

WHY (why this exists) → WHAT MUST BE TRUE (what must stay true) → HOW (how it works) → CAN WE
PROVE IT (how we know it works) → CAN WE MEASURE IT → CAN WE AUTOMATE IT (can it stop depending on
me?) → WILL IT SURVIVE (will it still be good tomorrow?). Clean Code is one possible answer to one of
these questions, not the question itself.

## 3. The fifteen questions

1. Why does this exist? 2. What problem are we really solving? 3. What must stay true?
4. What do we protect? 5. Where does the truth live? 6. What do we assume? 7. How do we know it's true?
8. Can we measure it? 9. Can we make verification deterministic? 10. Why does this need an LLM or a
human? 11. What happens when it changes? 12. What happens when it fails? 13. Can we reconstruct what
happened? 14. Could someone else understand it without the person who wrote it? 15. What legacy are we
creating?
And the closing one: are we making the system simpler, or just the code shorter? Is there a simpler
solution that meets the same conditions?

## 4. Hierarchy of what's protected

Each project declares it in `config/project.json`, in tie-break order. Every optimization answers which
property it improves and which it risks. Example from the origin project (unattended payments):
1. **Money**: neither more nor less; never charged without delivering, never delivered without charging.
2. **Transaction state**: a single source of truth that survives the process.
3. **Transaction identity**: one idempotency key per attempt; retry without duplicating.
4. **Integrity**: data crossing a boundary arrives whole or doesn't arrive.
5. **Auditability**: you can reconstruct what happened, when, with what data, and what the software
   decided.
6. **Recoverability**: after a crash the system returns to a known state.
7. **Security**: nothing sensitive ever leaves through an unforeseen channel.
8. **UX**: what the person sees, including speed.

## 5. Where the truth lives

Where does it live? Who can modify it? Who reads it? Who replicates it? How many versions exist? What
happens when they diverge? In critical flow the question isn't "which variable says PAID" but "what
evidence lets us claim it's paid".

## 6. Epistemic vocabulary

- **Measured**: there's a real number or trace, obtained by running the system or a deterministic script
  with a negative control and `tool_sha`; whatever the script flags as a heuristic stays Inferred.
- **Tested**: a test or guard asserts it and fails if it stops being true.
- **Inferred**: deduced from indirect evidence or from reading the code without running it.
- **Assumed**: taken as true without evidence; the owner of the assumption is written down.
- **Unknown**: nobody knows today; how to find out is written down.
An agent never raises a tag without new evidence. A tag drops when its evidence dies. Every citation
carries the sha it was read at. Cite the statement, never the comment.

## 7. Every change leaves future context

Code, tests, invariants, decisions, evidence, metrics, and explicit limits. Longevity questions for
every decision: what happens if the provider changes, the API, the hardware, the domain model, the
volume, the team? Can another engineer modify it without the person who created it?

## 8. What kind of intelligence does this task need

If it can be computed: script. If it can be checked deterministically: test or checker. If it needs
interpretation: specialized agent. If it needs an architectural decision: human with an agent.
How much intelligence do we need to buy to answer this question? That decides the model.
