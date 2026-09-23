# 03-tools

Deterministic static-analysis tools, portable across projects (read-only
over the repo they analyze: they never write or `git add` there). Python
3.11 stdlib, Java 21, sh = bash `set -euo pipefail`.

## Layout

- `bin/`: orchestrators: `fetch-tools.sh`, `metrics.sh`, `cartography.sh`,
  `clean-pass.sh`, `verify-commit.sh`, `verify-sectors.sh`, `benchmark-release.sh`,
  `install-claude.sh`, `sync-instance.sh`, `adaptar.sh`.
- `mcp/`: `metodo` MCP server (JSON-RPC over stdio, stdlib): `catalog.py` is
  the tool table; each one wraps a script from `lib/` or `bin/`.
- `hooks/`: Claude Code hooks (path and gate guards, budget, output
  validation, session state, ledger); `hooks.settings.json` is what the
  installer merges into `.claude/settings.local.json`.
- `lib/`: one module per tool; `baseline.py` (I/O), `repo_scan.py` and
  `toolenv.py` are the common base; `worktree.sh` is the only lib in bash.
- `config/`: `project.json` is the only file a new project fills in
  (docs_root, shared_build_files, money_paths, property_order,
  invariant_prefix, language); the rest of `config/*.json` ships a minimal
  generic placeholder, with its full instance over a critical-flow domain in
  `config/examples/critical-flow/`.
- `schemas/`: informal descriptions (change-card, role-contract), the round
  schemas (findings, blindspots, claims, verdict, brief, handoff), the
  receipt (`receipt`) and each role's output (`verification`, `*-output`).
- `baselines/`, `out/`, `vendor/`: generated, gitignored.
- `tests/`: one `unittest` per `lib/` module, with a negative control.

## Invocation

```bash
bin/adopt.sh <repo> <audit-folder> [--critical-flow-example]   # bootstraps config/project.json
bin/install-claude.sh <repo> [--tools D] # agents, skills, .mcp.json, hooks; --uninstall removes the kit's
bin/sync-instance.sh <instancia>         # copies lib/bin/schemas/mcp/hooks/tests to an instance, never config/
python3 mcp/server.py --selftest         # initialize + tools/list in-process
python3 lib/rdd_receipt.py status --repo <repo>   # start | capture | finalize | acknowledge | validate
python3 lib/rdd_risk.py --repo <repo> --base origin/develop [--change-card F]
python3 lib/test_sectors.py <repo> [--base B] [--check-verify <repo>/tools/verify/verify.sh]
bin/verify-sectors.sh <repo> [--base B] [--tasks a,b]  # sector battery under the Gradle lock
python3 lib/hooks_report.py              # ledger figures and the warn -> block criterion
bin/fetch-tools.sh                       # detekt, PMD, ktlint -> vendor/
python3 lib/shape_metrics.py <repo> [--modules a,b]
python3 lib/duplication_cpd.py <repo> --calibrate     # fixes config/cpd.json (deliberate change)
python3 lib/duplication_cpd.py <repo> [--min-tokens N] [--files a.kt,b.kt]
python3 lib/dep_boundaries.py <repo> [--config config/dep-boundaries.json]
python3 lib/domain_invariants.py <repo> [--config config/invariants-checks.json]
python3 lib/role_contract_validator.py --contract <c>.contract.json --repo <r> (--range A..B | --worktree D)
python3 lib/findings_schema_validator.py <json> --schema schemas/<name>.schema.json
python3 lib/change_card_validator.py [--extract] <file|->
python3 lib/docs_lint.py config/docs-caps.json
bin/metrics.sh <repo>                    # shape_metrics + duplication_cpd + delta vs baselines/latest
bin/cartography.sh <repo>                # + hotspots (90d) + merge-tree vs the integration branch
bin/clean-pass.sh <repo>                 # union of flagged rows, proposes nothing
bin/verify-commit.sh <repo> <range> [--full]     # tools/verify/verify.sh per commit, in a worktree
bin/benchmark-release.sh <repo> <refA> <refB> [--force-recompute]
python3 -m unittest discover tests
```

## Determinism

Every payload goes out through `lib/baseline.py::write_json`
(`sort_keys=True, indent=2`, trailing newline, no timestamps/hostnames/home
paths) and carries `schema_version`, `tool_sha` (this kit's HEAD),
`tool_versions` (python/java/pmd/detekt/ktlint), `repo_sha` and
`repo_dirty`. Wall-clock time lives apart, in `out/<repo_sha>/run-meta.json`.
Paths inside payloads are relative to the analyzed repo's root, never
absolute. `baseline.delta()` refuses to compare two payloads with
different `tool_sha` (`"verdict": "VOID: tool drift"`, exit 2) unless
`--allow-tool-drift`.

## P2 (built into the build, not into this kit)

This kit is static analysis external to the build: nothing here replaces
lint, detekt/ktlint as a Gradle task, or a real CI gate. Wiring
`role_contract_validator`/`change_card_validator` into a real CI hook, and
any check that needs to compile (not just parse text), are out of scope
for this repo: they are P2, the responsibility of the project adapting the
kit, not of `03-tools`.
