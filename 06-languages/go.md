# Go conventions: official baseline + typical house rules

## 1. Source and hierarchy

Read on 2026-10-15. go.dev's release history lists go1.27.2 (released 2026-10-08) as the latest point
release, and the spec is headed "Language version go1.27 (May 26, 2026)" (Measured). Hierarchy, top wins:
the spec (https://go.dev/ref/spec) says what compiles and nothing about style; `gofmt` owns formatting;
Effective Go gives the idioms; Go Code Review Comments is the review checklist; Go Doc Comments defines
doc comment shape; the package overviews of `context`, `sync`, `sync/atomic`, and `testing` carry usage
rules of their own. Secondary, labeled as such: Google's Go Style Guide, which says of its own Best
Practices document: "These best practices are not canonical" (GSG#about). For anything none of them
cover, the project's `CONVENTIONS.md` rules.

## 2. What the official guide says, verbatim

Anchor keys (full URLs in Sources): EG Effective Go · CRC Code Review Comments · DC Go Doc Comments ·
ERR blog "Working with Errors in Go 1.13" · CTX `pkg.go.dev/context`. All quotes Measured (fetched).

| Topic | Exact quote | Anchor |
|---|---|---|
| Formatting | "let the machine take care of most formatting issues" | EG#formatting |
| gofmt | "Run gofmt on your code to automatically fix the majority of mechanical style issues" | CRC#gofmt |
| MixedCaps | "the convention in Go is to use MixedCaps or mixedCaps" | EG#mixed-caps |
| Package names | "packages are given lower case, single-word names" | EG#package-names |
| Initialisms | "ServeHTTP not ServeHttp" | CRC#initialisms |
| Handle errors | "Do not discard errors using _ variables." | CRC#handle-errors |
| Wrap with `%w` | "will have an Unwrap method returning the argument of %w" | ERR#wrapping-errors-with-w |
| Wrapping is a contract | "wrapping an error makes that error part of your API" | ERR#whether-to-wrap |
| `errors.Is` | "The errors.Is function compares an error to a value." | ERR#examining-errors-with-is-and-as |
| Don't panic | "Don’t use panic for normal error handling." | CRC#dont-panic |
| Libraries | "real library functions should avoid panic" | EG#panic |
| Error strings | "Error strings should not be capitalized" | CRC#error-strings |
| Consumer-side interfaces | "belong in the package that uses values of the interface type" | CRC#interfaces |
| Mocks | "Do not define interfaces on the implementor side of an API “for mocking”" | CRC#interfaces |
| Doc comments | "Every exported (capitalized) name should have a doc comment." | DC (intro) |
| Func doc | "A function’s doc comment should explain what the function returns" | DC#func |
| Receivers | "Don’t use generic names such as “me”, “this” or “self”" | CRC#receiver-names |
| Context first | "The Context should be the first parameter, typically named ctx" | CTX#pkg-overview |
| Context not stored | "Do not store Contexts inside a struct type" | CTX#pkg-overview |
| Goroutine lifetimes | "make it clear when - or whether - they exit." | CRC#goroutine-lifetimes |
| Zero values | "the zero value of each type can be used without further initialization" | EG#allocation_new |
| Defer | "Deferred functions are executed in LIFO order" | EG#defer |

## 3. What the official guide does NOT say

Absence claims, Inferred from the pages in Sources (none of them was found to say otherwise):
- **Where the irreversible effect lives.** `context` cancels work; no page says whether an operation
  committed just before cancellation must survive it, nor who owns retrying it.
- **Exact amount types.** No page addresses exact amounts. `math/big` "implements arbitrary-precision arithmetic (big
  numbers)" with `Int`, `Rat`, and `Float` (big#pkg-overview); the standard library has no decimal type.
- **Log structure.** `log/slog` "provides structured logging" (slog#pkg-overview), but neither EG nor
  CRC forbids `fmt.Println` or `log.Printf` in a library.
- **Exhaustiveness over closed sets.** The spec: "If no case matches and there is a "default" case, its
  statements are executed" (spec#Expression_switches); a missed constant compiles and does nothing.
- **Docs drift, Measured:** `go.dev/doc/modules/managing-dependencies` says `go mod tidy` "has no
  arguments except for one flag, -v"; the `cmd/go` reference documents `-diff`. The command reference wins.

## 4. Typical house rules (labeled as such)

- **Exact amounts never `float64`**: integers in the smallest unit in a named type (`type Units int64`) or a reviewed
  decimal library; the wire format never depends on locale or `%f`.
- **Closed states + exhaustiveness linter**: `type State uint8` with a `const` block; `switch` without
  `default` on critical paths so `exhaustive` flags a new state; no correlated `bool`s as a state.
- **Errors wrapped with context, checked by type**: `fmt.Errorf("submit %s: %w", id, err)` where the
  boundary adds meaning; callers use `errors.Is`/`errors.As`, never `==` or string matching. Wrap only
  what the API commits to (ERR#whether-to-wrap); otherwise `%v`.
- **`log/slog` through the project's handler**: no `fmt.Println`/`log.Printf` in library packages;
  key-value attributes, never interpolated foreign text.
- **No package-level mutable state**: dependencies enter through constructors or parameters; Google's
  guide: libraries "should not force their clients to use APIs that rely on global state" (GSG-BP).
- **Pure decisions, effects at the edge**: decision functions in their own package take and return
  values; IO, `time.Now`, and randomness arrive as parameters or small consumer-side interfaces.
- **DOC-001, comments only say why**: doc comments on exported names in complete sentences naming the
  symbol, as DC requires; never narrate the diff; the proposer leaves `NEEDS-COMMENT` for the gate.
- **Tests**: table-driven, asserting invariants (round-trip, idempotency), never which goroutine won;
  `go test -race` always in CI; `t.Parallel()` only where there is no shared fixture or global state;
  no `time.Sleep` to wait: block on the condition being asserted, or use `testing/synctest`.

## Concurrency

| Topic | Exact quote | Anchor |
|---|---|---|
| Slogan | "Do not communicate by sharing memory; instead, share memory by communicating." | EG#sharing |
| Its limit | "This approach can be taken too far." | EG#sharing |
| Memory model | "must serialize such access." · "Don't be clever." | mem#advice |
| Cancellation | "Failing to call the CancelFunc leaks the child and its children" | CTX#pkg-overview |
| errgroup | "canceled the first time a function passed to Go returns a non-nil error" | errgroup#WithContext |
| SetLimit | "limits the number of active goroutines in this group to at most n." | errgroup#Group.SetLimit |
| Leaks | "Goroutines are not garbage collected; they must exit on their own." | pipelines#stopping-short |
| Once | "Once is an object that will perform exactly one action." | sync#Once |
| Atomics | "better done with channels or the facilities of the sync package" | atomic#pkg-overview |
| Fake time | "Within a bubble, the time package uses a fake clock." | synctest#hdr-Time |

House rules:
- **One owner of state**: a mutable value belongs to one goroutine or sits behind one `sync.Mutex` in
  the same struct; never read under one lock and written under another.
- **CAS, never check-then-act**: a guard touched from two goroutines is `atomic.Bool.CompareAndSwap` or
  a mutex-held section, never `if !started { started = true }`.
- **Cancellation always propagated**: every goroutine takes the caller's `ctx`; `defer cancel()` on the
  line after `WithCancel`/`WithTimeout`; no `context.Background()` below `main` or a test.
- **Cleanup exactly once**: `defer` for the single-path release, `sync.Once` (or `sync.OnceFunc`) when
  success and cancellation can both reach it.
- **Bounded goroutines**: `errgroup` with `SetLimit` or a fixed worker pool; never one per input.
- **`sync/atomic` only for counters and flags**: an invariant across fields takes a mutex.
- **Irreversible effects never lost**: a critical or hardware event goes through a channel whose sender
  blocks; never `select { case ch <- ev: default: }`, which drops on purpose.

## 5. How it's checked

Not run in this session: names and flags verified against each tool's docs page only (Inferred).

| Rule | Cheap detector | Better detector |
|---|---|---|
| Formatting, import groups | `gofmt -l .` (empty output) | `goimports -l .` |
| Suspicious constructs, lost `cancel` | `go vet ./...` (`lostcancel`) | `staticcheck ./...` |
| Data races | `go test -race ./...` (executed paths only) | plus `testing/synctest` for timing |
| `==` on errors, missing `%w` | golangci-lint `errorlint` | `wrapcheck` for external errors |
| Exhaustive closed sets | golangci-lint `exhaustive` | `gochecksumtype` for sealed interfaces |
| Context hygiene | golangci-lint `containedctx`, `contextcheck` | `noctx` for HTTP calls |
| `fmt.Println` in libraries | golangci-lint `forbidigo` (`^fmt\.Print`) | `sloglint` |
| `t.Parallel` hygiene | golangci-lint `tparallel` | `paralleltest` |
| Known vulnerabilities | `govulncheck ./...` | `govulncheck -mode binary <bin>` |
| `go.mod`/`go.sum` drift | `go mod tidy -diff` (non-zero exit on diff) | `go mod verify` |
| Exact amounts not `float64` | grep `float64` in critical packages + negative control | Unknown: no linter verified |

## Sources

All fetched with HTTP 200 and read on 2026-10-15.
- EG https://go.dev/doc/effective_go · CRC https://go.dev/wiki/CodeReviewComments
- DC https://go.dev/doc/comment · mem https://go.dev/ref/mem · spec https://go.dev/ref/spec
- Release history https://go.dev/doc/devel/release · ERR https://go.dev/blog/go1.13-errors
- CTX https://pkg.go.dev/context · https://go.dev/blog/context · https://go.dev/blog/context-and-structs
- pipelines https://go.dev/blog/pipelines · https://go.dev/security/best-practices
- Modules: https://go.dev/doc/modules/layout · https://go.dev/doc/modules/release-workflow ·
  https://go.dev/doc/modules/managing-dependencies · https://pkg.go.dev/cmd/go
- sync https://pkg.go.dev/sync · atomic https://pkg.go.dev/sync/atomic · https://pkg.go.dev/testing
- errgroup https://pkg.go.dev/golang.org/x/sync/errgroup · synctest https://pkg.go.dev/testing/synctest
- slog https://pkg.go.dev/log/slog · big https://pkg.go.dev/math/big · https://pkg.go.dev/cmd/vet
- Tools: https://pkg.go.dev/golang.org/x/tools/cmd/goimports · https://staticcheck.dev/docs/ ·
  https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck · https://golangci-lint.run/docs/linters/
- Secondary: GSG https://google.github.io/styleguide/go/ · GSG-BP
  https://google.github.io/styleguide/go/best-practices#global-state

## Verdict

Go gives half of the methodology for free: `gofmt` ends style debates, `error` values make failure
explicit, and `context` plus `errgroup` give work an owner and a cancellation signal. The other half is
house rules with external detectors: the compiler checks neither exhaustiveness nor exact amount types, and
the race detector only sees executed paths, so the critical flow rests on `exhaustive`, `-race` in CI,
and the integer-amount rule.
