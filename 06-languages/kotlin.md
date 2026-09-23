# Kotlin conventions: official baseline + typical house rules

## 1. Source and hierarchy

The official guide (https://kotlinlang.org/docs/coding-conventions.html) is the baseline and is not
restated. The project keeps its deltas in a committed `CONVENTIONS.md`, with a stable ID per rule and
declared detector (compiler, lint, guard test, script, human review) and status (active, silenced,
proposed). This document is the digest: when in doubt, the official guide or `CONVENTIONS.md` rules.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| Expression body | "Prefer using an expression body for functions with the body consisting of a single expression" | `fun foo() = 1` |
| Expression form | "Prefer using the expression form of try, if, and when" | `return if (x) a() else b()` |
| if vs when | "Prefer using if for binary conditions instead of when" / "Prefer using when if there are three or more options" | binary → `if`; ≥3 → `when` |
| Lambda outside | "If a call takes a single lambda, pass it outside parentheses whenever possible" | `list.filter { it > 10 }` |
| `it` | `it` in short, non-nested lambdas; explicit parameter when nested | |
| Named arguments | "when a method takes multiple parameters of the same primitive type, or for parameters of Boolean type" | `draw(x = 1, y = 2, fill = true)` |
| Immutability | "Prefer using immutable data to mutable. Always declare local variables and properties as val rather than var if they are not modified after initialization"; immutable collection interfaces in signatures; `listOf()` over `arrayListOf()` | `val`, `List<T>` in the signature |
| Higher order | "Prefer using higher-order functions (filter, map etc.) to loops. Exception: forEach (prefer using a regular for loop instead...)", with a cost clause | `for` loops to iterate without transforming |
| Extensions | "Use extension functions liberally... restrict the visibility of extension functions as much as it makes sense" | minimal visibility |
| Function vs property | property if it doesn't throw, is cheap, and returns the same thing without a state change | |
| Default values | over overloads | |
| Open ranges | `for (i in 0..<n)` | |
| Unit | the `Unit` return type is omitted | |
| Strings | templates over concatenation; multiline with `trimIndent` | |

## 3. What the official guide does NOT say

- Nothing about `sealed` (the word only appears in the modifier order list).
- Nothing about exhaustive `when` or about avoiding `else`.
- No criteria for choosing between `let`, `run`, `with`, `apply`, `also`: it defers to another page.
- Never the phrase "functional over imperative": the word "imperative" never appears.

So the slogan "functional before imperative" is replaced with three defensible rules: higher-order
functions before loops except `forEach`; expression form for `if`/`when`/`try`; `val` and immutable
collection interfaces by default, understanding the cost of each combinator in the critical flow.

## 4. Typical house rules (labeled as such)

- **Sealed + exhaustive `when` without `else`**: the compiler watches; an `else` swallows new cases.
- **Specific combinator before `fold`** (`partition`, `mapNotNull`, `firstOrNull`, `filterNot`);
  `fold` only when the accumulation IS the problem. **Fewer lines WITH more resolutions**: a three-branch
  `when` inside a `mapNotNull` beats a clever `fold` dragging a `Pair` accumulator.
- **Modeled data, not commented**: states and results as closed types; no correlated boolean flags
  nor magic strings acting as an enum; a state's name lives in the type, never in reflection on the
  class (obfuscators lie).
- **Effects at the edge, purity at the center**: small pure transformations in their own file,
  testable without a framework; IO, time, and randomness enter through parameters or interfaces.
- **Critical quantities in integer units and dedicated types** (`@JvmInline value class`), never
  `Double` nor a formatted `String`; the wire format doesn't depend on locale.
- **Auditability in the critical flow**: each data point's destination is readable at a glance.
- **Foreign text wrapped** (SDK messages, foreign exceptions, HTTP bodies) before interpolating it.
- **No raw logging** (`android.util.Log`, `println`, `printStackTrace`): everything through the
  project's facade.
- **Scope functions**: `apply` configures the receiver; `also` runs effects that return the receiver;
  `let` transforms a nullable; `run`/`with` group. Never nest three.
- **DOC-001, comments only if they say why**: in English, ≤ 30 words per sentence, only what the code
  can't say; KDoc on contracts; never narrate the diff; the proposer leaves `NEEDS-COMMENT` and the
  gate decides.
- **DOC-002, KDoc is a fragment that says what a caller needs**: the first sentence is a summary
  fragment, never `This method returns` nor `A Foo is a` (K8); a block tag that appears carries a
  description (K10); `@param` and `@return` only when the prose can't carry them (K5, B4). Presence
  stays DOC-001's question.
- **DOC-003, one action tag, and it carries a ticket**: `// TODO(DEV-123): what is missing and when it
  can go` (K17, T11); the accepted project keys live in `config/project.json:ticket_keys`, not in the
  rule; no bare `TODO`, no `FIXME`, no `STOPSHIP`, no person's name (K16); a tag with no ticket is
  untracked work and doesn't merge; `NEEDS-COMMENT` stays the gate's own marker and never merges either
  (T25).

  > House preference for KDoc, detector `generic-comment-gate` (human review), never a script flag and
  > never a merge block: verb first for functions, a noun phrase for types and properties (K8, L49, L50);
  > symbols in backticks, references in `[brackets]` (K1, K3). These two clauses are advisory on purpose.
  > Of 43 KDocs measured on 18-sep-2026, 27 open with a noun phrase and every one of them is correct under
  > K8, so a verb-first check would flag 27 compliant KDocs and 0 violations.

  Full evidence and measurement for DOC-002 and DOC-003 in `comentarios/research.md`.
- **MVI for new UI**: immutable `UiState`, pure JVM reducer whose case table is the spec, `Intent` =
  user verbs, `Event` = facts, irreversible effects never through the UI channel.
- **Compose as building blocks**: stateless components with state hoisting in a design module; the
  app composes.

## Concurrency

Coroutines, Flow, cooperative cancellation, actors or `Sendable` depending on the language, and the
concurrency house rules (single owner of state, CAS instead of check-then-act, exactly-once cleanup,
queues for what can't be lost) live in `concurrency-kotlin.md`, with their detectors.

## 5. How it's checked (detector → rule map)

| Rule | Cheap detector | Better detector |
|---|---|---|
| Exhaustive `when` | compiler | |
| Raw logging | project lint (`ForbiddenLogDetector`) + guard test | |
| New comments (DOC-001) | `comment_gate.py` (lists, measures, `--verify`) + `generic-comment-gate` | |
| KDoc shape (DOC-002) | `comment_gate.py` `kdoc_*` flags + `generic-comment-gate`; the verb-first and backtick clauses are advisory, human review only | detekt `EndOfSentenceFormat` / `OutdatedDocumentation` (P2, both off by default) |
| Action tags (DOC-003) | `comment_gate.py` `action_tags` field + `action_tag_*` flags, keys from `config/project.json` | detekt `ForbiddenComment` with `allowedPatterns` (P2) |
| Module purity | test that reads its own sources (forbidden imports) with a negative control | Konsist / detekt (P2) |
| Shape (length, `var`, `!!`, `lateinit`, `GlobalScope`) | `shape_metrics.py` (heuristic, Inferred) | detekt CLI |
| Duplication | `duplication_cpd.py` (PMD CPD, threshold in config) | |
| Dependency boundaries | `dep_boundaries.py` with nodes in config | Konsist (P2) |
| Critical quantities without `Double` | golden tests + grep in critical packages | |
| Coverage, mutation | need the build (P2) | Kover, Pitest in pure JVM modules |
