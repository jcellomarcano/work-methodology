# Contrasted research · how an agent makes its reply understandable to any human

Finding: four source families (official prompting guides, plain-language standards, executive communication
and cognitive science, research on analogies) agree, two by two or three by three, on four rules: conclusion
first, few chunks, no redundancy, tested with readers. No rule is backed by all four families at once. And no
provider guide imposes answer-first or a length cap on the model's OUTPUT: they talk about the prompt, with
two loose examples of output structure (G5, O12). That is why the identity is written outside the model and
measured with a script.

Simile: a pilot does not trust that the plane will "fly fine by default"; they carry a checklist and
instruments. The identity is the checklist; `output_lint.py`, the instruments. Unlike the plane, here the
instrument measures the shape of the reply, not whether the passenger understood the flight (that stays
unmeasured, see the minutes).

Full evidence, with literal quotes in their own language, in `sources/` (ids A/O/G, L, E, N). Measurement in
`minutes/2026-09-09-prueba-en-frio.md`. Everything below is a reading of those quotes [Inferido], except where noted.

## 1. Where the four families agree

| Rule that emerges | Providers | Plain language | Executive and cognitive | Analogies |
|---|---|---|---|---|
| The main point first | prompt only (A18, G2, G15) | L5, L12, L32, L43, L44 | E1, E3, E9, E14, E43 | |
| Few chunks, grouped | | L15, L17, L41 | E17, E29, E30, E31, E42 | |
| No redundancy or filler | A12, A13, G8, G12, O25 | L22, L16 | E24, E34, E38 | |
| Explicit, verifiable instruction | A14, A26, O6, G11 | L20, L35 | | N10 (explicit mapping) |
| Reader's own words; term defined once | | L19, L20, L35, L45 | | N11, N26, N28 |
| Test with readers, not formulas | A15 (colleague with no context) | L7, L8, L25, L47, L48 | | N26, N28 |
| Analogy with declared mapping and limit | | | | N5, N7, N10, N11, N13 |

## 2. Where they differ, and what we decided

| Tension | Who says what | Decision in the identity | Why |
|---|---|---|---|
| Sentence length | 25 words (L29, L41) versus 15-20 (L45) | warns at 25, fails at 40 | the 25-word rule is the only one with two sources and holds for English (L41); Spanish runs a bit longer [Asumido] |
| How many points | 7 ± 2 (E27) versus 3-5 (E30, E31, E17) | cap of 5 top-level bullets | Cowan corrects Miller and Minto recommends 3; 5 is the ceiling, not the target |
| Reading level | age 9 (L37), 8th grade (L46), no level (L7, L26) | no numeric level; everyday words and a term defined once | ISO and Digital.gov warn against writing for a grade without looking at the audience; the reader here is anyone |
| Readability formulas | rejected (L7, L47) versus used as a proxy (L40, L46) | no formula; shape counts (sentences, bullets, layers) | formulas fail on lists and fragments (L47, L48), which is the shape of nearly all LLM output |
| Lists or prose | Anthropic suppresses lists (A9, A10); Google asks for lists (G5) | lists only for discrete items or steps; prose to explain | it is the only reading compatible with L24, L41 and A9 at once |
| BLUF or narrative | answer first (E1, E5) versus a 6-page memo (E44, E45) | answer first, always; the long narrative only in the technical layer and on demand | Amazon's memo requires committed time in a room; a chat does not have that |
| SCQA or pure BLUF | situation before the answer (E15) versus answer first (E1, E6) | BLUF; one line of context only if the reader lacks it | the "early abandonment" rule (E43) outweighs it |
| How many analogies | explicit mapping of one (N10, N11) versus several for something complex (N6, N7, N12) | one explicit at a time; for something complex, a second one compared against the first | the sources support both at once; "one per concept" as a general rule has no support and is not adopted |
| Positive or negative | say what to do (A6) versus both (G13) | positive instructions | it is the common denominator and avoids contradictions (A27, O16) |
| Length control | parameter (O9, O18) versus prompt (A13, G9) | requested in the block; the parameter is set in the adapter | the block has to be vendor-agnostic; the parameter belongs to the provider |

## 3. What nobody says (and why we impose it from outside)

- No provider gives guidance for a non-technical audience or reading level: the only documented adaptation is
  a text-to-speech case (A22). That is why the identity declares the reader (any human) and the two layers.
- None gives a length cap for replies to humans or an "answer first" rule for the output: the ordering rules
  are about the prompt (A18, G15, O23). That is why COM-01 and COM-03 are house rules and are measured.
- The plain-language standards do not cover machine-generated text: no preambles, no coverage-hedging
  phrases, no rule for defining a term once across a conversation (L19). That is why COM-06 and COM-07 exist.
- Nobody studies whether personalized analogies improve comprehension: the evidence is indirect (N31, N32,
  N33). That is why the owner's own personal-language file is declared [Asumido] and kept out of the public block (COM-14).
- Nobody measures format drift except OpenAI (O13). That is why the GPT adapter repeats the instruction.

## 4. Identity design, decision by decision

| Decision | Sources |
|---|---|
| One single, vendor-agnostic block, thin per-provider adapters | A1, O2, G2 (the role sits in the system layer); A24, O30, G21 (short); A29, G21 (importable) |
| Two layers with the fixed heading `## Detalle técnico` / `## Technical detail` | E43, E46, E47 (progressive disclosure); L14 (do not mix audiences); G5 (executive summary + detail) |
| Answer in the first line, no preamble | E1, E3, E14, E43; L5, L12, L32 |
| Five points maximum in the human layer | E30, E31, E17 |
| Length proportional to the question, no hard cap | owner's decision; E7 and E38 suggest one screen, noted as a reference |
| One-idea sentences, 25 words as a warning, 40 as a failure | L15, L29, L35, L41, L45; the 40 is a house threshold [Asumido] |
| Everyday word; term defined once | L19, L20, L35; N26, N28 (curse of knowledge) |
| No filler or repeating close | E24 (redundancy), E34, L22 |
| Epistemic tag only in the technical layer | methodology §0; E23 (claim and source together) |
| `Siguiente paso` / `No probado` per type, in the human layer | L13, L34 (the reader's task); methodology §10; adversarial round B-01 and C-05 |
| The irreversible rises to the human layer (COM-18); clarification or refusal as its own type | adversarial round B-01, B-02, B-19; why-layer §4 |
| Analogy with mapping and limit, one at a time | N2, N3, N4 (relational structure); N10, N11, N13 (where it breaks); N5, N7 (explicit mapping); N6, N12 (second one for something complex) |
| Everyday analogies for the general public; personal ones only for the declared interlocutor | N11 (familiar base); N31, N32 (personalization, moderate evidence) |
| Positive instructions with no contradictions | A6, A27, O16, O26 |
| Minimal markdown | A7 (mirrors the prompt), A9, O11, O12 |
| The human's language | CONTEXT-PACK §4 |
| Measured by script, not by a readability formula | methodology §12; L7, L47, L48 |

## 5. What was measured

Cold test with Haiku, Sonnet and Opus, five fixed prompts, with and without identity (v2), same lint: PASS
1/15 without identity versus 8/15 with it; median word count 362 versus 231; technical layer present 0/15
versus 11/15 [Medido, `bench/summary.json`]. The lint measures obedience to the block, not comprehension: the
arm with identity is scored against rules only it received, so the effect is partly tautological. What stays
unmeasured (GPT, Gemini, local models, real human comprehension, n > 1) is in the minutes. The Feynman
technique, which shows up in almost every "explain it simply" tip, is not Feynman's: it is a 2011 construction
(N16, N19); the documented anecdote is Goodstein's (N20). It is used as a self-test, not as a citation.

## Verdict

The identity invents nothing: most rules have two or more independent sources (COM-17 has one; COM-08 and
COM-18 come from the methodology itself and from the adversarial round), and where sources contradict each
other the decision is written down with its reasoning. What makes it vendor-agnostic is that it asks for
nothing a provider does not document as obeyable (role in the system layer, explicit positive instructions,
format shown by example) and that the check does not depend on the model. The honest gap: it measures shape,
not comprehension; closing that needs human readers, not more prompts.
