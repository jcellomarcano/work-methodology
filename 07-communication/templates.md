# Templates by reply type

Six skeletons. Always the same shape: human layer on top, `## Detalle técnico` / `## Technical detail` below
only when needed. What sits between `<>` gets filled in; what does not apply is deleted, never left empty.
That every skeleton passes the lint with its `--type` is proven by `03-tools/tests/test_output_lint.py`
(`test_every_template_skeleton_passes_its_type`), not by this sentence. The examples are in English; in
Spanish only the markers change (`Siguiente paso:`, `Necesito de ti:`, `No probado:`, `Lo que NO es:`,
`## Detalle técnico`). The skeleton tags (`[Medido]`, `[Inferido]`...) are examples: use whichever fits each claim.

## 1. Question (`--type pregunta`)

```markdown
<Answer in one sentence.>

<Why, in one to three sentences. Analogy only if the concept is new, with its mapping and its limit.>

## Detalle técnico
- <claim with file:line@sha, command or figure> [Medido]
- No probado: <what remains unverified and how to verify it>
```

Example:

```markdown
No: the retry would double the charge, because the idempotency key is generated inside the loop.

Every attempt is born with a new key, so the provider sees it as a separate payment. It is like
pulling a new ticket at the deli: if you get a new number every time you ask, you get served twice.
Unlike the deli, here the second time costs money.

## Detalle técnico
- `PaymentRetry.kt:52` @ 9f3e2a1 calls `newIdempotencyKey()` on every iteration [Medido]
- The test `retry_keeps_key` does not exist; it would go in `PaymentRetryTest.kt` [Desconocido]
- No probado: the provider's behavior with two keys under 1 s apart
```

## 2. Status / progress (`--type estado`)

```markdown
<Where the task stands, in one sentence with a number if there is one.>

- Done: <what closed and is green>
- Left: <what remains, in order>
- Blocked by: <what is stopping progress and who owns it>

Siguiente paso: <the concrete action and when>
No probado: <what has not been verified yet>

## Detalle técnico
- <commit, branch, test, measurement> [Probado]
```

## 3. Recommendation or decision (`--type decision`)

```markdown
I recommend <option>, because <the property it protects> outweighs <what it risks>.

| Option | What it improves | What it risks | Cost |
|---|---|---|---|
| A <name> | <property> | <property> | <time or money> |
| B <name> | <property> | <property> | <time or money> |

Necesito de ti: <the exact decision only the owner can make, and by when>

## Detalle técnico
- <evidence for each cell in the table> [Inferido]
- No probado: <what the comparison did not measure>
```

Table rule: one property from the project's hierarchy in each improvement and risk cell, never an adjective.
Option rows count like COM-03's bullets: five at most, and past the fourth it is better moved to the
technical layer.

## 4. Failure report (`--type fallo`)

```markdown
<Symptom as the person sees it: what they did, what they expected, what happened.>

Cause: <one sentence, with the evidence next to it>.
Lo que NO es: <the ruled-out hypotheses and why>.

Siguiente paso: <proposed fix or missing data, and who does it>

## Detalle técnico
- <log with timestamp, file:line@sha, measurement> [Medido]
- <how it was reproduced, exact command> [Medido]
- No probado: <what is missing to close the cause>
```

## 5. Research report (`--type investigacion`)

```markdown
<Main finding in one sentence.>

<Concrete simile, if the topic is new to the reader: what maps to what in daily life, and where it breaks.>

- Coinciden: <what the sources agree on>
- Difieren: <where they contradict each other, and why>
- Nadie dice: <the gap that matters for the decision>

No probado: <sources not reached, unverified claims>

## Detalle técnico
- "<literal quote in its own language>" (<source>, <URL>) [Medido]
- <figure with its source> [Inferido]
```

Research rule: every quote is copied literally and in its own language; a quote that could not be read on
its own page is `[Inferido]` (snippet) or `[Desconocido]`, never `[Medido]`. The simile comes before the
contrast when the reader does not know the topic, and after it when they do.

## 6. Clarification or refusal (`--type aclaracion`)

When a fact is missing to answer, or the requested action is irreversible and needs confirmation, or it
should not be done: the first line is the question or the no, never an invented answer for the sake of
having one.

```markdown
<The exact missing question, or "I won't do X because Y", in one sentence.>

<What changes depending on the answer, in one to three sentences; if it is irreversible, say so here.>

Necesito de ti: <the data or the confirmation, and what happens if it does not arrive>
```

## What the lint requires per type

| Type | Requires `Siguiente paso` / `Necesito de ti` in the human layer | Requires `No probado` / `Lo que NO es` in the human layer |
|---|---|---|
| pregunta | no | no |
| estado | yes | yes |
| decision | yes | no |
| fallo | yes | yes |
| investigacion | no | yes |
| aclaracion | yes | no |

Everything else (answer first, five bullets at most, short sentences, no filler, a tag per unit in the
technical layer, no repeating close, minimal format, the irreversible in the human layer) is required across
all six types. A marker with empty content ("Siguiente paso: none") warns: the marker is a string, not a commitment.
