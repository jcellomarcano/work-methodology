# Python conventions: official baseline + typical house rules

## 1. Source and hierarchy

There isn't a single document: PEP 8 (https://peps.python.org/pep-0008/) is the baseline style guide,
PEP 20 (https://peps.python.org/pep-0020/) is language design philosophy, not a PR checklist, and
static typing arrived later in separate PEPs (484, 526, 557, 586, 634), each with its own scope. When
in doubt: PEP 8 for style, the specific PEP for each typing mechanism, and the project's own
`CONVENTIONS.md` for what none of them cover.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| Consistency with judgment | "A Foolish Consistency is the Hobgoblin of Little Minds" (section title, PEP 8) | following a rule without judgment is worse than breaking it |
| Consistency hierarchy | "Consistency within a project is more important. Consistency within one module or function is the most important" (PEP 8) | the project's style overrides PEP 8 |
| Grouped imports | "Imports should be grouped in the following order: 1. Standard library imports. 2. Related third party imports. 3. Local application/library specific imports" (PEP 8) | fixed order, blank line between groups |
| Comparison with None | "Comparisons to singletons like None should always be done with `is` or `is not`, never the equality operators" (PEP 8) | `is None`, never `== None` |
| Boolean comparison | "Don't compare boolean values to True or False using `==`" (PEP 8) | `if greeting:`, not `if greeting == True:` |
| Untyped `except` | "A bare `except:` clause will catch SystemExit and KeyboardInterrupt exceptions, making it harder to interrupt a program with Control-C" (PEP 8) | at most `except Exception:` |
| Line length | "Limit all lines to a maximum of 79 characters" (PEP 8), with a team escape hatch: "it is okay to increase the line length limit up to 99 characters" | recommendation, not a mandate |
| Explicit over implicit | "Explicit is better than implicit" (PEP 20) | language design, not a lint rule |
| Errors never silent | "Errors should never pass silently. Unless explicitly silenced" (PEP 20) | an exception caught on purpose, never by omission |
| Annotations aren't executed | "no type checking happens at runtime" (PEP 484) | annotating doesn't validate; a separate checker is needed |
| Syntax for variables | "This PEP aims at adding syntax to Python for annotating the types of variables... instead of expressing them through comments" (PEP 526) | replaces `# type:` comments |
| What a dataclass is | "Data Classes can be thought of as 'mutable namedtuples with defaults'" (PEP 557) | mutable by default, not a value object per se |
| `frozen=True` | "by passing `frozen=True` to the `@dataclass` decorator you can emulate immutability" (PEP 557) | it emulates; Python has no real object immutability |
| `Literal` | "Literal types indicate that some expression has literally a specific value" (PEP 586) | typing the exact value, not just the broad type |
| `match` | "The match statement first evaluates the subject expression" (PEP 634) | structure, with no exhaustiveness guarantee of its own |

## 3. What the official guide does NOT say

- PEP 8 says nothing about functional versus imperative programming.
- PEP 8 does not mention `dataclasses`, `Decimal`, or `Enum`: they're later mechanisms.
- Line length is a recommendation with an explicit escape hatch for teams, not a hard limit.
- No typing PEP requires running a checker: the interpreter never validates an annotated type.
- `match` doesn't require exhaustiveness: without `case _`, an uncovered value does nothing, silently.

## 4. Typical house rules (labeled as such)

- **`@dataclass(frozen=True)` for critical quantities and states**: immutable value objects where the
  protected property is state or identity, not just the mutable container PEP 557 gives.
- **`Enum` and `Literal` for closed states**: no magic strings or correlated booleans acting as a
  state. Modeled data, not commented.
- **Exhaustive `match` with `assert_never`** (`typing_extensions` or `typing` 3.11+): closes the gap
  PEP 634 leaves open, so an uncovered case stops failing silently.
- **Money in `decimal.Decimal` or integers in the smallest unit**: never `float`. Critical quantities
  in exact types.
- **`pathlib` over `os.path`**, **`logging`, never `print`**: no raw logging, everything through a
  facade.
- **`mypy --strict` or `pyright` in strict mode in CI**, not optional: typing only protects when
  enforced, PEP 484 leaves it voluntary.
- **Never a bare `except:`**; catch the concrete type or `Exception` as a ceiling.
- **Context managers for every edge effect**: files, network, time, randomness enter through a
  parameter or `with`, never implicitly inside a function that should be pure.
- **Pure functions in their own module, with doctest or pytest**, testable without booting the system.
- **Deterministic JSON output** (`sort_keys=True`) in any project tool: same input, same bytes, so an
  output diff is the detector.

## 5. How it's checked

| Rule | Cheap detector | Better detector |
|---|---|---|
| PEP 8 style (naming, length) | `ruff check` | `flake8` + `pylint` |
| Formatting | `ruff format` | `black --check` |
| Strict typing | `mypy --strict` | `pyright --strict` |
| Bare `except`, `eval`, unsafe subprocess | `ruff` rules (bugbear/security) | `bandit` |
| Non-exhaustive `match` | `mypy` + `assert_never` | human review in PR |
| Boundaries between modules | grep of forbidden imports with a negative control | `import-linter` |
| Invariants (idempotency, round-trip) | `pytest` with golden cases | `hypothesis` (property-based) |
| Output determinism | test comparing exact bytes | versioned golden file |

## Concurrency (structured asyncio, threads, and 3.13)

| Rule | Official text | Reading |
|---|---|---|
| `TaskGroup` | "An asynchronous context manager holding a group of tasks" (asyncio-task docs) | groups tasks under a single life cycle, not a loose `gather` |
| Failure in the group | "The first time any of the tasks belonging to the group fails with an exception... the remaining tasks in the group are cancelled... those exceptions are combined in an ExceptionGroup" (asyncio-task docs) | one failure cancels the rest; the real error is an `ExceptionGroup`, never an isolated exception |
| `asyncio.timeout` | "Return an asynchronous context manager that can be used to limit the amount of time spent waiting on something" (asyncio-task docs, since 3.11) | the deadline is set by the primitive, not by a `sleep` loop |
| Cancellation is re-raised | "In case asyncio.CancelledError is explicitly caught, it should generally be propagated when clean-up is complete" (asyncio-task docs) | `CancelledError` is re-raised after `finally`, never absorbed |
| Locks don't cross threads | "asyncio primitives are not thread-safe, therefore they should not be used for OS thread synchronization" (asyncio-sync docs) | `asyncio.Lock` protects within a loop, not across OS threads |
| GIL | "The mechanism used by the CPython interpreter to assure that only one thread executes Python bytecode at a time" (glossary, term-global-interpreter-lock) | `threading` gives IO concurrency, not CPU parallelism |
| Free-threading (3.13) | "CPython now has experimental support for running in a free-threaded mode... This is an experimental feature" (What's New in 3.13); PEP 703 defines the `--disable-gil` build | opt-in and experimental; don't assume the GIL is absent in production |

House rules:
- `TaskGroup` over `asyncio.gather` for every group of related tasks: one failure cancels the rest and the error is visible in full in the `ExceptionGroup`, not truncated to the first exception.
- `asyncio.create_task` always with the reference kept: the documentation warns "Important: Save a reference to the result of this function" because the loop only holds a weak reference and the task can vanish mid-execution if nothing else references it.
- Deadline with `asyncio.timeout`, never with `sleep` in a polling loop: the deadline is decided by the code with a signal, not a repeated question.
- `CancelledError` is always re-raised; an `except Exception` doesn't catch it (it subclasses `BaseException`), but an `except BaseException` that doesn't re-raise does swallow it and breaks cooperative cancellation.
- Bounded `asyncio.Queue` for events that can't be lost, with the producer blocking instead of dropping; never an unbounded list acting as a buffer.
- Mutation of shared state within a single owning task or under `asyncio.Lock`; never read in one task and write in another without the primitive.
- No blocking IO inside the loop: `run_in_executor` or `asyncio.to_thread` for what isn't native `async def`; `concurrent.futures.ProcessPoolExecutor`/`multiprocessing` for what's CPU-bound, because the GIL doesn't free real CPU between threads.
- The kit's scripts are single-threaded on purpose (output determinism, see `00-principles`): structured concurrency is for services, not for the deterministic pipeline this document requires.

Detectors: `ruff` with the `ASYNC1xx`/`ASYNC2xx` rules (flake8-async) for polling `sleep` and `except` that swallows cancellation; `python -X dev` or `PYTHONASYNCIODEBUG=1` for slow callbacks and never-awaited coroutines; `pytest-asyncio` with an explicit `asyncio.Runner` in tests. No native thread sanitizer for `threading`: there's no ThreadSanitizer equivalent in CPython's standard toolbox (an honest, unresolved finding).

## Sources

- https://peps.python.org/pep-0008/
- https://peps.python.org/pep-0020/
- https://peps.python.org/pep-0484/
- https://peps.python.org/pep-0526/
- https://peps.python.org/pep-0557/
- https://peps.python.org/pep-0586/
- https://peps.python.org/pep-0634/
- https://docs.python.org/3/library/asyncio-task.html
- https://docs.python.org/3/library/asyncio-sync.html
- https://docs.python.org/3/glossary.html#term-global-interpreter-lock
- https://peps.python.org/pep-0703/
- https://docs.python.org/3/whatsnew/3.13.html
- https://docs.python.org/3/howto/free-threading-python.html

## Verdict

Python separates decision and effect poorly by design: nothing in the language pushes IO to the edge,
so that boundary has to be drawn by hand with pure functions in their own module and strict typing in
CI. The auditability of the critical flow depends on three house rules (frozen dataclass, `Decimal`,
exhaustive `match`), none of which PEP 8 requires.
