# SQL conventions: official baseline + typical house rules

## 1. Source and hierarchy

ISO/IEC 9075 defines the SQL language (syntax and semantics), not a writing style, and it isn't an
openly accessible text citable line by line. There's no official style guide equivalent to PEP 8.
The three de facto ones this document uses, with no hierarchy among them, are the SQL Style Guide by
Simon Holywell (https://www.sqlstyle.guide/), Mozilla's guide for its telemetry
(https://docs.telemetry.mozilla.org/concepts/sql_style), and GitLab's
(https://handbook.gitlab.com/handbook/enterprise-data/platform/sql-style-guide/). Where they agree,
the rule is strong. Where only one states it, it's marked as such.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| Uppercase keywords | "Always use uppercase for the reserved keywords like SELECT and WHERE" (sqlstyle.guide); "selecting Key words, Data Types and Functions to always be upper case" (GitLab) | `SELECT`, `WHERE`, `JOIN` in uppercase |
| Alias with `AS` | "Always include the AS keyword" (sqlstyle.guide); "Use the AS operator when aliasing a column or table" (GitLab) | never an implicit alias |
| Meaningful alias | "Should relate in some way to the object or expression they are aliasing" (sqlstyle.guide) | no `t1`, `t2` |
| snake_case | "Use lower case names with underscores, such as first_name. Do not use camelCase" (Mozilla); "All field names should be snake-cased" (GitLab) | column and table names in snake_case |
| No reserved words as names | "Ensure the name is unique and does not exist as a reserved keyword" (sqlstyle.guide); "Avoid key words like date or month as a column name" (GitLab) | avoid `date`, `order`, `user` alone |
| Explicit JOIN | "Always include the JOIN type rather than relying on the default join" (Mozilla); "Prefer explicit join statements" (GitLab) | `INNER JOIN`, never an implicit comma |
| CTE over nested subquery | "Do not use nested queries. Instead, use common table expressions to improve readability" (Mozilla); "Prefer CTEs over sub-queries as CTEs make SQL more readable and are more performant" (GitLab) | CTE by default for queries with more than one level |
| Column formatting | "Commas between SELECT elements should always be at the end of the line" (Mozilla) | one column per line, comma at the end |
| Prefixed booleans | "Boolean field names should start with has_, is_, or does_" (GitLab) | flag naming, not just type |
| Timestamps in UTC | "Timestamps should end with `_at` and should always be in UTC" (GitLab) | explicit time zone in the name and in the data |

## 3. What the official guide does NOT say

- None of the three say anything about which column type to use for money.
- None say anything about transactions or isolation levels.
- None say anything about migrations, schema versioning, or how to undo one.
- None say anything about idempotency keys to avoid a duplicate write.
- None explicitly forbid `SELECT *` outside the context of debugging a CTE.
- ISO/IEC 9075 defines what a transaction is, but not when to use each isolation level in a concrete
  system: that's an architecture decision, not the standard's.

## 4. Typical house rules (labeled as such)

- **`NUMERIC`/`DECIMAL` or integers in the smallest unit, never `FLOAT`/`DOUBLE` for money**: a
  critical quantity in an exact type, none of the three guides mention it.
- **Constraints ARE the invariants**: `NOT NULL`, `CHECK`, `UNIQUE`, `FOREIGN KEY` with the invariant's
  id in the constraint's name or in a `COMMENT`, not only in a separate document.
- **Idempotent migrations**: `IF NOT EXISTS`, one up/down pair per migration, one migration one idea,
  checksum verified before applying. Schema recoverability, not just data recoverability.
- **Transaction with an explicit isolation level for everything irreversible** (a charge, a balance
  adjustment, a payment state change): never the engine's implicit default.
- **Idempotency keys as a `UNIQUE constraint`**, not as an application-level check: the database is
  where the truth lives, and the constraint makes it impossible to violate by accident.
- **Append-only ledgers**: audit rows with no `UPDATE`, only inserting the next correction.
- **Explicit column lists, never `SELECT *`** outside debugging an intermediate CTE.
- **Deterministic `ORDER BY` on anything feeding a report or a diff**: without an explicit order the
  engine promises no stability, and a diff over a variable order says nothing.
- **`TIMESTAMPTZ`, not `TIMESTAMP` without a zone**: and explicitly distinguish wall clock from
  monotonic clock when measuring duration.
- **Business logic in triggers, never without a test**: an untested trigger is an invisible effect in
  the critical flow.
- **`EXPLAIN` before adding an index on the critical path**: the indexing decision is evidenced, not
  guessed.

## 5. How it's checked

| Rule | Cheap detector | Better detector |
|---|---|---|
| Style (uppercase, alias, commas, JOIN) | `sqlfluff lint` | `sqlfmt` as a format gate |
| Constraints as invariants | reading the DDL in PR | `pgTAP` / `pytest-postgresql` with a negative control |
| Idempotent migrations | dry-run in CI against a schema copy | migration linter (`squawk` for Postgres) |
| Money types | grep for `FLOAT`/`DOUBLE` in money-column DDL | `schema diff` in CI against a baseline |
| Deterministic `ORDER BY` in reports | grep for missing `ORDER BY` in report views | golden test of ordered output |
| Index on the critical flow | `EXPLAIN` pasted in the change card | `EXPLAIN ANALYZE` in a test-bench environment |

## Concurrency (isolation, locking, idempotency under a race)

| Rule | Official text | Reading |
|---|---|---|
| MVCC | "each SQL statement sees a snapshot of data (a database version) as it was some time ago... providing transaction isolation for each database session" (PostgreSQL, mvcc-intro) | isolation by version, not by universal locking |
| Read Committed | "a SELECT query... sees only data committed before the query began" (PostgreSQL, transaction-iso) | Postgres's default level; sees changes between statements |
| Serializable and retry | "applications using this level must be prepared to retry transactions due to serialization failures" (PostgreSQL, transaction-iso) | SERIALIZABLE requires a retry policy, it's not free |
| `FOR UPDATE` | "causes the rows retrieved... to be locked as though for update... until the current transaction ends" (PostgreSQL, explicit-locking) | explicit row lock for read-modify-write |
| `SKIP LOCKED` | "any selected rows that cannot be immediately locked are skipped... to avoid lock contention with multiple consumers accessing a queue-like table" (PostgreSQL, sql-select) | a job-queue pattern, not general reading |
| Application locks | "advisory locks... the system does not enforce their use, it is up to the application to use them correctly" (PostgreSQL, explicit-locking) | a mechanism separate from constraints, not a substitute |
| Deadlock | "PostgreSQL automatically detects deadlock situations and resolves them by aborting one of the transactions involved" (PostgreSQL, explicit-locking) | expected by design, not a bug to avoid at all costs |
| `ON CONFLICT` | "specifies an alternative action to raising a unique violation... DO NOTHING simply avoids inserting a row... DO UPDATE updates the existing row" (PostgreSQL, sql-insert) | atomic upsert, replaces check-then-insert |

Other engines differ: MySQL InnoDB uses REPEATABLE READ by default ("This is the default isolation level for InnoDB", https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html); SQLite serializes writers at the file level ("SQLite uses locks to serialize the writes automatically", https://www.sqlite.org/isolation.html).

House rules:
- Idempotency keys as a `UNIQUE constraint` and `INSERT ... ON CONFLICT DO NOTHING/UPDATE`, never a check `SELECT` followed by an `INSERT`: the window between the two statements is the race.
- A balance's read-modify-write goes INSIDE a single transaction, with `FOR UPDATE` or an atomic `UPDATE ... SET balance = balance + ?`; never read in one statement and write in a later one.
- SERIALIZABLE or explicit locking for everything irreversible (a charge, a payment state change), with a finite retry and only over idempotent statements.
- `SKIP LOCKED` for job queues (outbox) with `claimed_by`/`claimed_at` visible on the row; never an unmarked `SELECT` that lets two consumers repeat the work.
- `statement_timeout` and `lock_timeout` set by the code, never the engine's default: the deadline is decided by the project, not the engine.
- A deadlock is an expected design case: the code retries once with the same idempotency key and logs the SQLSTATE (40P01 deadlock, 40001 serialization failure).
- Append-only ledgers to avoid `UPDATE` contention on hot rows.
- Migrations adding constraints use `NOT VALID` + `VALIDATE CONSTRAINT`: "this potentially-lengthy scan is skipped... validation acquires only a SHARE UPDATE EXCLUSIVE lock" (ALTER TABLE), so as not to lock the table with a long scan.

Detectors: `pg_locks`/`pg_stat_activity` on a test bench under load; `log_lock_waits` enabled; pgTAP or pytest-postgresql with two connections deliberately racing over the same id; `squawk` as a migration linter for `ADD CONSTRAINT` without `NOT VALID`; `EXPLAIN (ANALYZE, BUFFERS)` before trusting a lock plan.

## Sources

- https://www.postgresql.org/docs/current/transaction-iso.html
- https://www.postgresql.org/docs/current/explicit-locking.html
- https://www.postgresql.org/docs/current/sql-select.html
- https://www.postgresql.org/docs/current/sql-insert.html
- https://www.postgresql.org/docs/current/mvcc-intro.html
- https://www.postgresql.org/docs/current/sql-altertable.html
- https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html
- https://www.sqlite.org/isolation.html

## Verdict

In SQL, the "pure decision" is the query itself, with no effect until it runs; the effect is the
transaction wrapping it and the commit that makes it irreversible. No style guide gives the critical
flow's auditability: constraints as invariants and the append-only ledger do.
