# Concurrency in Kotlin: coroutines, Flow, and the measured house rules

## 1. Source and hierarchy

The official coroutines guide (https://kotlinlang.org/docs/coroutines-guide.html, with its chapters
"coroutines-basics", "coroutines-cancellation", "coroutines-flow", "exception-handling",
"coroutine-context-and-dispatchers", "shared-mutable-state-and-concurrency") covers Kotlin 2.x with
kotlinx.coroutines 1.9.x through 1.11.x. The guide was rewritten between 2024 and 2026: several Flow
operators (`conflate`, `collectLatest`, `callbackFlow`, `awaitClose`, exception transparency) and
`Dispatchers.Main.immediate`/`limitedParallelism` are no longer in the guide's prose, only in the API's
KDoc (kotlinlang.org/api/kotlinx.coroutines/...); both sources count as official, KDoc rules when the
guide is silent. Version facts verified in the project's CHANGES.md: 1.9.0 (Kotlin 2.0) introduces
`Flow.chunked` and promotes `limitedParallelism` to stable; 1.10.0 updates to Kotlin 2.1.0 and
introduces `Flow.any/all/none`; 1.11.0 updates to Kotlin 2.2.20 and fully rewrites the concurrency and
error-handling KDoc. No CHANGES.md for those versions records a coroutine semantics change tied to the
K2 compiler; that point is Inferred, not Measured.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| Structured concurrency | "new coroutines can only be launched in a CoroutineScope that defines and manages their lifecycle" | no scope, no `launch`/`async` |
| Lightweight coroutines | "This makes coroutines much lighter than threads and allows running millions of them in one process" | they aren't threads, but they aren't free either |
| Cooperative cancellation | "coroutine cancellation is cooperative" | nothing gets cancelled if the code doesn't cooperate |
| Explicit check | "isActive... returns false when the coroutine is canceled"; "ensureActive()... throws a CancellationException" | a long loop with no suspension must check |
| Timeout | "A timeout allows you to automatically cancel a coroutine after a specified duration" | `withTimeoutOrNull` |
| CancellationException | "It indicates normal cancellation of a coroutine. It is not printed to console/log by default" | it isn't an error, it's the stop signal |
| supervisorScope | "propagates the cancellation in one direction only and cancels all its children only if it failed itself" | one child's failure doesn't kill its siblings |
| Non-cancellable block | "NonCancellable is useful when you need to ensure that certain operations... complete even if the coroutine is canceled" | `withContext(NonCancellable)` in `finally` |
| Cold Flow | "Like sequences, cold flows are lazy"; "Usually flows represent cold streams" | each `collect` re-runs the block |
| flowOn | "changes only the coroutine context of the upstream flow while keeping the downstream flow in the caller's context" | the producer's context, not the collector's |
| buffer | "You can change the buffer capacity with the .buffer() operator" | decouples emitter and collector speed |
| conflate | "the emitter is never suspended due to a slow collector, but collector always gets the most recent value emitted" | drops intermediate values on purpose |
| collectLatest | "when the original flow emits a new value then the action block for the previous value is cancelled" | cancels in-flight work, doesn't queue it |
| callbackFlow/awaitClose | "Using awaitClose is mandatory in order to prevent memory leaks when the flow collection is cancelled" | without `awaitClose` the channel closes too early |
| Exception transparency | "Flow machinery enforces exception transparency at runtime and throws IllegalStateException on any attempt to emit a value, if an exception has been thrown" | `emit` inside a `catch` is forbidden |
| StateFlow | "Updates to the value are always conflated"; "always collects the most recently emitted value" | serves "latest state", not events |
| SharedFlow | "shares emitted values among all its collectors in a broadcast fashion"; "keeps a specific number of the most recent values in its replay cache" | broadcast with replay, not point-to-point queueing |
| Mutex | "Mutual exclusion for coroutines" | a suspendable alternative to `synchronized` |
| Dispatchers.Main.immediate | "executes coroutines immediately when it is already in the right context... without an additional re-dispatch" | avoids an unnecessary UI frame jump |
| limitedParallelism | "Creates a view of the current dispatcher that limits the parallelism to the given value" | throttling without creating a new pool |
| runTest | "this function behaves similarly to runBlocking, with the difference that the code that it runs will skip delays" | virtual time, not `Thread.sleep` |

## 3. What the official guide does NOT say

- Nothing about where the irreversible effect lives (persistence, network, hardware): the guide
  covers the mechanism (`Job`, `Flow`, `Mutex`), never the architectural boundary.
- Nothing about foreign SDK callbacks: neither `@Volatile`, nor memory barriers, nor CAS appear in the
  guide; `shared-mutable-state-and-concurrency.html` shows `Mutex` but never says when to use CAS
  instead of a lock.
- Nothing about idempotency under retry nor about a transition journal: `CancellationException`
  documents the stop signal, not what to do with partially finished work.
- The choice between `Flow`/`Channel`/`StateFlow`/`SharedFlow` for events that can't be lost is a
  house decision: the KDoc describes each one's behavior (conflation, replay, `DROP_OLDEST`) but never
  says which one to use for money.

## 4. Typical house rules (labeled as such)

- **Owner and cancellation of the work**: no anonymous `CoroutineScope(...)` nor `GlobalScope` on a
  terminal path; every `launch`/`async` hangs off a scope someone cancels. Without an owner, there's
  no "nothing irreversible without an owner".
- **Persisted state computed inside the `transform`**: it's computed INSIDE `DataStore.updateData` or
  the equivalent `transform`, never read outside and written afterward; with 200 concurrent writers,
  read-outside-write-inside left 2 records where 200 were expected (a measured case). One source of
  truth, one owner of the write.
- **CAS, never check-then-act**: every field a foreign SDK callback can touch from another thread
  carries `@Volatile` or `kotlin.concurrent.atomics` (experimental since Kotlin 2.1.20), and the guard
  is `compareAndSet`/`putIfAbsent`, never an `if (!started) { started = true; ... }`.
- **The deadline is ours, and the edge is a signal**: timeouts with `withTimeoutOrNull` over our own
  work; the asynchronous boundary with a foreign SDK is resolved with `CompletableDeferred` or
  `Channel`, never with a boolean flag polled in a loop.
- **SDK init under a `Mutex`**: two overlapping startups aren't two independent attempts, they're a
  race; the `Mutex` serializes startup (a measured case: an overlapping session left an NFC reader
  blocked until a physical restart).
- **Exactly-once cleanup**: every `finally` that releases a resource after cancellation runs under
  `withContext(NonCancellable)`, with a `settled` guard that prevents double release when cancellation
  and success race each other.
- **`CancellationException` is never swallowed**: a `catch (e: Exception)` around suspended code
  checks `if (e is CancellationException) throw e` before any handling; otherwise structured
  cancellation stops propagating and the parent never finds out.
- **`Channel` for what can't be lost, `SharedFlow`/`StateFlow` for state**: a money event over
  `SharedFlow` with `onBufferOverflow = DROP_OLDEST` gets lost by design; `Channel` applies
  backpressure instead of dropping.
- **`runBlocking` outside `main()` and tests is a smell**: on the main thread it blocks the UI; in
  production, a `runBlocking` on a terminal path is the simplest way to turn structured concurrency
  into a deadlock.

## 5. How it's checked (detector → rule map)

| Rule | Cheap detector | Better detector |
|---|---|---|
| `GlobalScope`/anonymous scope/`runBlocking` outside tests | shape script (grep + lightweight AST) | detekt (`GlobalCoroutineUsage`, custom rule) |
| Injected dispatcher, not hardcoded | detekt `InjectDispatcher` | PR review |
| Redundant `suspend` / mistyped `Flow` return | detekt (`RedundantSuspendModifier`, `SuspendFunWithFlowReturnType`) | compiler with `-Werror` |
| `Thread.sleep` in suspended code | detekt `SleepInsteadOfDelay` | Android lint |
| Swallowed `CancellationException` | golden test that cancels a parent scope and expects propagation | `kotlinx-coroutines-debug` / `DebugProbes.dumpCoroutines()` |
| Coroutine leaks or deadlocks | `DebugProbes` in integration tests | `kotlinx-lincheck` for custom concurrent structures |
| `Flow` behavior (order, cancellation, conflation) | Turbine (`test { }`) | golden test with `runTest` + `TestDispatcher` |
| Virtual time in tests | `runTest` + `StandardTestDispatcher` | `TestCoroutineScheduler.advanceUntilIdle()` |
| Real CAS vs check-then-act | grep for `if (!x) { x = true }` over `@Volatile` fields | human review in critical-flow PR |

## Sources

- https://kotlinlang.org/docs/coroutines-guide.html
- https://kotlinlang.org/docs/coroutines-basics.html
- https://kotlinlang.org/docs/coroutines-cancellation.html
- https://kotlinlang.org/docs/coroutines-flow.html
- https://kotlinlang.org/docs/exception-handling.html
- https://kotlinlang.org/docs/coroutine-context-and-dispatchers.html
- https://kotlinlang.org/docs/shared-mutable-state-and-concurrency.html
- https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines/-cancellation-exception/index.html
- https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines.flow/conflate.html
- https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines.flow/collect-latest.html
- https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines.flow/callback-flow.html
- https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines.flow/-flow/index.html
- https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines.flow/-state-flow/index.html
- https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines.flow/-shared-flow/index.html
- https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines.sync/-mutex/index.html
- https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines/-main-coroutine-dispatcher/immediate.html
- https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-core/kotlinx.coroutines/-coroutine-dispatcher/limited-parallelism.html
- https://kotlinlang.org/api/kotlinx.coroutines/kotlinx-coroutines-test/kotlinx.coroutines.test/run-test.html
- https://kotlinlang.org/docs/whatsnew2120.html
- https://github.com/Kotlin/kotlinx.coroutines/blob/master/CHANGES.md

## Verdict

Coroutines give an owner (`Job`/scope) and a cooperative cancellation signal: half of "effects at the
edge, pure decision at the center" comes free in the language primitive. But the guide is silent on
journaling, idempotency, and CAS versus check-then-act: that other half, the one that makes process
death mid-payment safe, is still a house rule with its own detector.
