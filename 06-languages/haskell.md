# Haskell conventions: official baseline + typical house rules

## 1. Source and hierarchy

There's no official Haskell style guide: no language committee stands behind any of the style guides
in circulation, unlike PEP 8 for Python. The two de facto references are Johan Tibell's guide
(https://github.com/tibbe/haskell-style-guide/blob/master/haskell-style.md) and Kowainik's
(https://kowainik.github.io/posts/2019-02-06-style-guide), each a convention from one author or one
team, not a standard. The real, mechanical enforcement comes from GHC warnings (`-Wall`) and `hlint`,
not from any guide's prose.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| Line length | "Maximum line length is 80 characters" (Tibbe) | 80 columns |
| Explicit or qualified imports | "Always use explicit import lists or qualified imports for standard and third party libraries. This makes the code more robust against changes in these libraries" (Tibbe) | never a bare `import Foo` |
| No warnings | "Code should be compilable with -Wall -Werror. There should be no warnings" (Tibbe) | the build fails on any warning |
| Aligned constructors | "Align the constructors in a data type definition" (Tibbe) | fixed `data` formatting |
| Records with a single constructor | "Records for data types with multiple constructors are forbidden" (Kowainik) | a type with more than one constructor doesn't use record syntax |
| Name casing | "lowerCamelCase for function and variable names. UpperCamelCase for data types, typeclasses and constructors" (Kowainik) | casing convention per category |
| Descriptive names | "Do not use ultra-short or indescriptive names like a, par, g unless the types of these variables are general enough" (Kowainik) | name follows the domain, not brevity |
| Haddock on top-level functions | "Comment every top level function (particularly exported functions), and provide a type signature; use Haddock syntax in the comments" (Tibbe) | documented contract, not narrated implementation |
| Line comments | "Separate end-of-line comments from the code with 2 spaces" (Kowainik) | formatting, not content |

## 3. What the official guide does NOT say

- Neither guide says anything about how to model money.
- Neither says anything about where IO should live or about effect architecture.
- Neither explicitly forbids partial functions (`head`, `fromJust`, `undefined`) in the text.
- Neither mentions property-based testing, `QuickCheck`, or `hedgehog`.
- Neither is a language standard: they're conventions from one author (Tibbe) or one team (Kowainik),
  citable as a reference, not as a norm.

## 4. Typical house rules (labeled as such)

- **`newtype` for every critical quantity** (`newtype Money = Money Integer` in the smallest unit),
  never `Double`: a critical quantity in an exact type, no guide requires it.
- **Sum types with total pattern matching**, `-Wincomplete-patterns -Werror` in the project's flag
  set: modeled data as closed types, the compiler watches for the new case.
- **Pure core, effects at the edge**: a transition function that returns `State`/`Either`, with IO,
  time, and randomness behind an IO boundary or a minimal interface, never inside the function that
  decides.
- **`Either`/typed errors in the core, never exceptions**: the decision is read from its return type,
  not from what it might throw at runtime.
- **`Text` over `String`**: performance aside, it avoids foreign text poorly wrapped in char lists.
- **Smart constructors, never partial functions in critical code** (`head`, `fromJust`, `undefined`):
  `relude` or the `-Wname-shadowing`/`-Wincomplete-record-updates` warnings as an early alert, not a
  production crash as the detector.
- **Deterministic serialization**: `aeson` with a fixed key order via `toEncoding`, so an output diff
  is a byte-for-byte comparison, not JSON reordered by the runtime.
- **Property tests for invariants** (`QuickCheck`/`hedgehog`): idempotency, round-trip, quantity
  conservation, each with its own negative control.
- **Haddock only on contracts**: what the function guarantees, never narrating the diff nor
  justifying the change to the reviewer.

## 5. How it's checked

| Rule | Cheap detector | Better detector |
|---|---|---|
| Zero warnings | `-Wall -Werror` | `-Wall -Wincomplete-patterns -Wincomplete-uni-patterns -Werror` |
| Style (imports, layout, naming) | `hlint` | `ormolu`/`fourmolu` as a format gate |
| Partial functions in critical code | grep for `head`/`fromJust`/`undefined` in money packages, with a negative control | `stan` |
| Dead code | PR review | `weeder` |
| Invariants (idempotency, conservation) | `QuickCheck` with fixed cases | `hedgehog` with shrinking and a negative control |
| Serialization determinism | golden test of exact bytes | CI comparison against a versioned baseline |

## Concurrency (STM, async, asynchronous exceptions)

| Rule | Official text | Reading |
|---|---|---|
| STM | "Software Transactional Memory: a modular composable concurrency abstraction", referencing the paper "Composable memory transactions" (Harris, Marlow, Peyton Jones, Herlihy) (`stm` package, Control.Monad.STM) | composable transactions, not a loose `IORef` |
| `atomically` | performs "a series of STM actions atomically" (Control.Monad.STM) | all or nothing; never impure IO inside the block |
| `retry` | used when the transaction "has seen values in TVars which mean that it should not continue" and blocks until they change (Control.Monad.STM) | declarative wait on state, not manual polling |
| `forkIO` | "Creates a new thread... The new thread will be a lightweight, unbound thread" (Control.Concurrent) | a lightweight thread managed by the runtime, not an OS thread |
| `MVar` | "Haskell threads can communicate via MVars, a kind of synchronised mutable variable" (Control.Concurrent) | a synchronized variable, not a generic lock |
| `async`/`withAsync` | "No exception is swallowed... No thread is leaked"; `withAsync` cancels the child "via uninterruptibleCancel" on leaving the scope (`async` package) | a lexical scope that kills the child, never an orphan thread |
| `concurrently`/`race` | if one action fails or wins, the other is cancelled automatically (`async` package) | neither leaves an extra thread running |
| Asynchronous exceptions | "thrown by external events" and only caught within `IO`; `mask`/`uninterruptibleMask` protect a critical section (Control.Exception) | another thread's cancellation can arrive at any unmasked point |
| `bracket` | acquires, runs, and guarantees release "even if an exception occurs" (Control.Exception) | exactly-once release under cancellation |
| Modern structured concurrency | the `ki` package describes itself as "a lightweight structured concurrency library" | an alternative to manual `async` scopes, same principle |

House rules:
- Shared state with invariants in STM (`check`/`retry` inside the transaction), never `IORef` with separate reads and writes: the race disappears because the runtime retries the whole transaction.
- `bracket`/`finally` for every release that must happen exactly once, even under asynchronous cancellation thrown by another thread.
- Scopes with `withAsync` or `ki` so that no thread outlives its creator; no loose `forkIO` without an owner that awaits or cancels it.
- Deadlines with `System.Timeout.timeout` or `race`, never a thread that sleeps and polls.
- The pure core returns `Either`; asynchronous exceptions only appear at the `IO` edge, never crossing the decision function.
- `-threaded +RTS -N` declared explicitly on the executable that needs it, never implicit.
- Bounded `TQueue`/`TBQueue` with backpressure for events that can't be lost; without a bound, the buffer is a silent drop disguised as a queue.

Detectors: `-Wall -Werror` (plus `-Wincomplete-patterns`); `dejafu` for systematic testing of concurrency interleavings; `ThreadScope` or the runtime eventlog to spot orphan threads; `hlint`/`stan` in review; `-fno-omit-yields` so a tight loop doesn't block cooperative cancellation.

## Sources

- https://hackage.haskell.org/package/stm
- https://hackage.haskell.org/package/base/docs/Control-Concurrent.html
- https://hackage.haskell.org/package/async
- https://hackage.haskell.org/package/base/docs/Control-Exception.html
- https://hackage.haskell.org/package/ki

## Verdict

Haskell is the language that most facilitates "pure decision at the center, effects at the edge": the
type system separates `IO` from the rest with no discipline required. But no style guide forces you to
exploit it: the critical flow's auditability depends on the house rules (`newtype` for money, total
sum types, deterministic serialization), not on the compiler alone.
