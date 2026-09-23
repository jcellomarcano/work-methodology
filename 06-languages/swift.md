# Swift conventions: official baseline + typical house rules

## 1. Source and hierarchy

The Swift API Design Guidelines (https://www.swift.org/documentation/api-design-guidelines/) are the
official naming and API design guide, maintained by swift.org. It isn't a formatting guide: that's
covered by swift-format (https://github.com/swiftlang/swift-format), a tool from the Swift project
itself. The Google Swift Style Guide (https://google.github.io/swift/) is third-party, broader in
formatting and practices, and serves as a secondary source where the official one is silent. The
Swift book's Language Guide
(https://docs.swift.org/swift-book/documentation/the-swift-programming-language/) documents value
semantics (struct/enum) but doesn't prescribe style. When in doubt: API Design Guidelines for names,
swift-format for formatting, the project's own `CONVENTIONS.md` for the rest.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| Central goal | "Clarity at the point of use is your most important goal" | the name is read at the call site, not the declaration |
| Clarity over brevity | "Clarity is more important than brevity" | minimizing characters isn't a goal |
| Omit needless words | "Omit needless words" | don't repeat what the type already says |
| Name by role | "Name variables, parameters, and associated types according to their roles, rather than their type constraints" | the name describes what it does, not what type it is |
| Terminology | "Use Terminology Well" (heading); avoid obscure terms when a common word exists, precedent over simplifying for beginners | |
| Methods over free functions | "Prefer methods and properties to free functions" | a free function only when there's no obvious `self` or an established domain notation |
| Mutating/nonmutating pairs | `-ed`/`-ing` suffix for the nonmutating version of the mutating imperative verb | `x.sorted()` vs `x.sort()` |
| Booleans as assertions | "Uses of Boolean methods and properties should read as assertions about the receiver when the use is nonmutating" | `isEmpty`, `line1.intersects(line2)` |

## 3. What the official guide does NOT say

- Nothing about architecture (MVVM, TCA, Clean).
- Nothing about error handling beyond naming (`try`/`throws` vs `Result` is a project decision).
- Nothing about formatting: indentation, line length, braces; that's swift-format or the Google guide.
- Nothing about functional vs imperative: the word "imperative" never appears.
- The Google Swift Style Guide does address force unwrap ("Force-unwrapping and force-casting are
  often code smells and are strongly discouraged"), but it's a third-party guide, not swift.org's
  official one.

## 4. Typical house rules (labeled as such)

- **struct/enum with associated values for closed states**: an exhaustive switch, no `default`; a
  new case breaks the build, not the runtime.
- **Value semantics for domain models**: immutable struct/enum where identity doesn't matter; class
  only when reference identity is the actual requirement.
- **Decimal or integers in the smallest unit for money, never `Double`**: `Double`'s binary rounding
  isn't a detail, it's a money bug.
- **Never `!` or `try!` in the critical flow**: `guard let`, `Result`, or a typed `throws` at the
  edge; forcing is only accepted in tests or after an already-proven precondition.
- **`Codable` with explicit `CodingKeys` and `.sortedKeys`**: the wire key doesn't depend on the
  Swift property's name, and the output is deterministic for diffing.
- **Effects at the edge with actors or structured concurrency**: IO, network, and time enter through
  an injected actor or an `async` function, never triggered from a computed property.
- **`os.Logger` (unified logging), never `print`**: everything through the project's facade; `print`
  has no levels and can't be filtered in production.
- **No singletons with mutable state**: `static let shared` only for something truly stateless or
  injected; hidden shared state breaks "where the truth lives".

## Concurrency

Coroutines, Flow, cooperative cancellation, actors or `Sendable` depending on the language, and the
concurrency house rules (single owner of state, CAS instead of check-then-act, exactly-once cleanup,
queues for what can't be lost) live in `concurrency-swift.md`, with their detectors.

## 5. How it's checked (detector → rule map)

| Rule | Cheap detector | Better detector |
|---|---|---|
| `!` / `try!` in non-test code | SwiftLint (`force_unwrapping`, `force_try`) | human review in PR |
| Length and complexity | SwiftLint (`file_length`, `function_body_length`, `cyclomatic_complexity`) | custom regex rule |
| Formatting | `swift-format lint` | strict-mode CI |
| Unsafe concurrency | compiler flag (`-strict-concurrency=complete`) | Thread Sanitizer |
| Silenced warnings | `-warnings-as-errors` | PR review |
| Domain invariants | XCTest with golden cases + negative control | property-based testing |
| Dead code | grep for unused symbols | Periphery |

## Sources

- https://www.swift.org/documentation/api-design-guidelines/
- https://google.github.io/swift/
- https://docs.swift.org/swift-book/documentation/the-swift-programming-language/
- https://github.com/swiftlang/swift-format
- https://github.com/peripheryapp/periphery

## Verdict

The API Design Guidelines govern naming, not architecture: nothing pushes the pure decision to the
center or the effect to the edge on its own. Value semantics and actors provide the tool, but that
boundary is drawn by hand with house rules (Decimal, no `!`, Logger); the critical flow's
auditability depends on those rules, not on the official guide.
