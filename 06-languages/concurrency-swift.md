# Concurrency in Swift: actors, Sendable, and the measured house rules

## 1. Source and hierarchy

The concurrency chapter of the Swift Programming Language book
(https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/) is the
semantic baseline: async/await, actors, `Sendable`, cooperative cancellation. The Swift 6 migration
guide (https://www.swift.org/migration/documentation/migrationguide/) documents the language mode and
full concurrency checking. Swift Evolution proposals (github.com/swiftlang/swift-evolution) are the
normative source for each new mechanism: actors, `Sendable`, `sending`, `Mutex`, low-level atomics,
default isolation in Swift 6.2; the vision document "Improving the approachability of data-race
safety" frames why SE-0461/SE-0466/SE-0470 exist. WWDC sessions are cited as contextual guidance,
never as a normative source (Inferred: no verified verbatim transcript). When in doubt: the exact
proposal > the book > this digest.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| Native support | "Swift has built-in support for writing asynchronous and parallel code in a structured way" | no external library needed |
| Actors share state safely | "Actors let you safely share information between concurrent code" | an actor owns its mutable state |
| Sendable | "A type that can be shared from one concurrency domain to another is known as a sendable type" | crossing domains requires `Sendable` |
| Cooperative cancellation | "Swift concurrency uses a cooperative cancellation model. Each task checks whether it has been canceled at the appropriate points" | nothing gets cancelled if nothing checks |
| Cancellation check | "the tasks need to check for cancellation... by calling checkCancellation(), or by reading the isCancelled property" | two forms, same obligation |
| Structured concurrency | "this approach is called structured concurrency" (parent-child hierarchy, propagated cancellation) | a cancelled parent cancels its children |
| Swift 6 language mode | "the compiler can now guarantee that concurrent programs are free of data races" | opt-in per module, not global |
| Complete checking | "Show how to enable complete concurrency checking for Swift 5 projects" | `-strict-concurrency=complete` before mode 6 |
| Sendable / closures (SE-0302) | "Sendable and @Sendable closures" | types crossable between domains, closures included |
| Actors (SE-0306) | "Actors" | mutable-state isolation as a language type |
| Global actors (SE-0316) | "Global actors" | `@MainActor` and custom global actors |
| Region-based isolation (SE-0414) | "Region based Isolation" | moving a non-Sendable value if its region becomes disconnected |
| Isolation inheritance (SE-0420) | "Inheritance of actor isolation" | a nested function inherits the actor of whoever declares it |
| `sending` (SE-0430) | "`sending` parameter and result values" | a value can cross the boundary exactly once |
| `Mutex` (SE-0433) | "Synchronous Mutual Exclusion Lock" | a synchronous lock when an actor doesn't fit |
| Atomics (SE-0410) | "Low-Level Atomic Operations" | low-level primitives in the stdlib |
| `@isolated(any)` (SE-0431) | "`@isolated(any)` Function Types" | a function's type states which actor runs it |
| Default isolation (SE-0466) | "Control default actor isolation inference"; flag `-default-isolation MainActor` | the whole module goes to MainActor unless explicitly `nonisolated` |
| `nonisolated(nonsending)` (SE-0461) | "Run nonisolated async functions on the caller's actor by default" | no longer jumps to a global executor by default |
| Isolated conformances (SE-0470) | "Global-actor isolated conformances" | a `@MainActor` type can conform to protocols without being Sendable |

## 3. What the official guide does NOT say

- Nothing about where the irreversible effect lives: actors give memory isolation, they don't say
  whether the actor should also own the write to disk or network.
- Nothing about idempotency nor about a retry journal: cooperative cancellation says when to stop,
  never what to do with partial work.
- "MainActor by default" (SE-0466/SE-0461, Swift 6.2) is a per-module build decision
  (`-default-isolation MainActor`), not an editorial swift.org recommendation about architecture.
- Nothing about which foreign SDK deserves its own `CheckedContinuation` nor about a double-resume
  guard: that's the responsibility of whoever wraps the callback-based API.
- Nothing about `AsyncStream`/buffering policy for money events: the documentation describes the
  mechanism (`.bufferingNewest`, `.unbounded`), never which one to use when the event can't be lost.

## 4. Typical house rules (labeled as such)

- **Irreversible effect inside a single-owner actor**: the money store lives in its own actor; views
  read, they never write the protected state directly.
- **`Sendable` domain models** as immutable struct/enum; a `class` crossing actors without `Sendable`
  is the leak the Swift 6 compiler already blocks, but the design shouldn't rely only on the compiler
  to discover it.
- **Never `try!`/force on an async path**: `guard let`/typed `throws` at the edge; force only after an
  already-proven precondition, or in a test.
- **Cancellation checked at every suspension point of a critical loop**: `Task.checkCancellation()` or
  `isActive` inside the loop, not only on function entry.
- **`withTaskCancellationHandler` for exactly-once cleanup**: the cancellation handler doesn't replace
  `defer`, it complements it when work can be cancelled mid-`await`.
- **`Task.detached`/unstructured task only with an owner and a saved handle**: without someone holding
  the `Task` and able to cancel it, it's a `GlobalScope` under another name.
- **Never `DispatchQueue.sync` from an actor**: the actor already serializes its queue; syncing
  outward from inside is a recipe for deadlock.
- **The deadline is set by our code**: `withThrowingTaskGroup` racing against a `Task.sleep` or a
  clock, never polling a flag.
- **Foreign SDK callbacks bridged with a continuation that resumes exactly once**:
  `withCheckedThrowingContinuation` with a guard (`Bool`/lock) that prevents a double resume, which
  aborts the process at runtime.
- **`AsyncStream` with an explicit buffering policy**: `.bufferingNewest(1)` drops events by design
  and never serves money; there it's `.unbounded` with its own backpressure or a channel that doesn't
  drop.
- **Tests with clocks, never `Task.sleep`**: swift-testing's `ContinuousClock`/`TestClock` control time
  without sleeping the real test runner.

## 5. How it's checked (detector → rule map)

| Rule | Cheap detector | Better detector |
|---|---|---|
| Swift 6 language mode / complete checking | `-strict-concurrency=complete` or Swift 6 language mode as a compile error | Thread Sanitizer (`-sanitize=thread`) |
| Silenced warnings | `-warnings-as-errors` | PR review |
| `try!`/`!` in non-test code | SwiftLint (`force_try`, `force_unwrapping`) | human review on the critical flow |
| `DispatchQueue.sync` inside an actor | custom SwiftLint rule (regex) | PR review |
| Double continuation resume | Xcode runtime issue detection | golden test that forces the race |
| Actor isolation violated at runtime | Xcode runtime issue detection (actor isolation checking) | Thread Sanitizer |
| `Task.sleep` in tests | grep in the test target | swift-testing with `ContinuousClock`/`TestClock` |
| `AsyncStream` with `.bufferingNewest` on a money flow | grep in critical packages | human review on the critical flow |
| Unstructured task without a saved handle | grep for `Task.detached`/`Task {` with no assignment | PR review |

## Sources

- https://docs.swift.org/swift-book/documentation/the-swift-programming-language/concurrency/
- https://www.swift.org/migration/documentation/migrationguide/
- https://github.com/swiftlang/swift-evolution/blob/main/proposals/0302-concurrent-value-and-concurrent-closures.md
- https://github.com/swiftlang/swift-evolution/blob/main/proposals/0306-actors.md
- https://github.com/swiftlang/swift-evolution/blob/main/proposals/0316-global-actors.md
- https://github.com/swiftlang/swift-evolution/blob/main/proposals/0414-region-based-isolation.md
- https://github.com/swiftlang/swift-evolution/blob/main/proposals/0420-inheritance-of-actor-isolation.md
- https://github.com/swiftlang/swift-evolution/blob/main/proposals/0430-transferring-parameters-and-results.md
- https://github.com/swiftlang/swift-evolution/blob/main/proposals/0433-mutex.md
- https://github.com/swiftlang/swift-evolution/blob/main/proposals/0410-atomics.md
- https://github.com/swiftlang/swift-evolution/blob/main/proposals/0431-isolated-any-functions.md
- https://github.com/swiftlang/swift-evolution/blob/main/proposals/0466-control-default-actor-isolation.md
- https://github.com/swiftlang/swift-evolution/blob/main/proposals/0461-async-function-isolation.md
- https://github.com/swiftlang/swift-evolution/blob/main/proposals/0470-isolated-conformances.md
- https://github.com/swiftlang/swift-evolution/blob/main/visions/approachable-concurrency.md
- https://developer.apple.com/videos/play/wwdc2025/268/ (Inferred, contextual guidance not verbatim)

## Verdict

Actors and `Sendable` give a default memory owner, and the compiler watches it from Swift 6 mode
onward: half of "one single source of truth" comes from the language. But the model is silent on
persistence, idempotency, and which SDK needs a double-resume guard: that other half, the one that
makes process death mid-payment safe, is still a house rule with its own detector.
