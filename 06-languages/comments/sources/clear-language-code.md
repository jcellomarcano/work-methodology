# Sources · plain language, the clauses that apply to a reader of source code

This file does not repeat the plain-language dossier. The full table of L1 to L48 lives in
`../../../07-communication/sources/lenguaje-claro.md` and its ids are cited by reference here. Two clauses
were fetched for this round and get new ids, L49 and L50.

Read on 18-sep-2026 with `curl`. Tags: [Measured] read on the page.

## 1. New ids

| Id | Source | Topic | Literal quotation | URL | Tag |
|---|---|---|---|---|---|
| L49 | Digital.gov, Writing for understanding, "Use the present tense" | verb form | "The simplest and strongest form of a verb is present tense." | https://digital.gov/guides/plain-language/writing | [Measured] |
| L50 | Digital.gov, Writing for understanding, "Avoid hidden verbs" | verb form | "Use the strongest, most direct form of the verb possible." / "Verbs are the fuel of writing - they give your sentences power and direction." / "Too often, we hide verbs by turning them into nouns, making them less effective and using more words than we need." / "A hidden verb (or nominalization) is a verb converted into a noun." | = L49 | [Measured] |

L49 and L50 share a page with L18, which already quotes the active-voice clause from it. They are
separate clauses under separate subheadings, so they get separate ids rather than extending L18.

## 2. Existing ids, mapped to the reader of source code

No new id was needed for the rest. The plain-language family already states every clause this round
uses; the contribution is the mapping, not new evidence.

| Existing id | Clause, in one line | What it governs in code |
|---|---|---|
| L5, L12, L32, L43 | the most important message goes first | K2 and K7: the KDoc summary is the first paragraph, and it is the only part some readers see |
| L15 | "Express only one idea in each sentence." | one KDoc summary fragment, one idea; a second idea goes in the detailed description |
| L18 | "Active voice makes it clear who should do what." | a KDoc summary says what the declaration does, not what "is done" |
| L19 | jargon versus a necessary technical term defined once | a comment may use `EMV`, `SoftPos` or `DEV-327`; it defines a term the codebase does not already own |
| L21 | "Don't define something that's obvious to the user" | the plain-language root of DOC-001 and of Android's self-explanatory exception (K12) |
| L22 | "You can confuse your audience if you use different terms for the same concept or object." | one term per concept, the same rule iso-24495-code states as T19 |
| L29, L35, L41 | split sentences over 25 words | the warning threshold for a comment sentence |
| L33 | headings: "start them with a verb when possible" | the nearest plain-language support for a verb-first KDoc summary; it is about headings, not fragments, so it is an analogy and not a citation for a hard rule |
| L45 | "Sentences should be no more than 15-20 words." | the stricter reading of the same threshold |
| L47, L48 | readability formulas fail on short fragments and lists | why no formula scores a comment; a comment is a fragment, which is also T23's reason |

## 3. What this family does not cover

- Nothing on code. Every source in the dossier assumes a document or a web page. iso-24495-code
  (T15 to T21) exists precisely because the standard stops at prose, and it says so itself (T16).
- Nothing on a summary that must fit one line in an IDE index (K7).
- Nothing on block tags, backticks, or symbol links (K3, K5, K10).
- Nothing on a marker that tracks unfinished work (K16, T11).
- The 25-word clause is stated for English (L41). Comments here are English by DOC-001, so the
  clause applies without the language caveat that the prose identity had to carry.
