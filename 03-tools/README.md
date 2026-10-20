# 03-tools

Deterministic static-analysis tools, portable across projects (read-only
over the repo they analyze: they never write or `git add` there). Python
3.11 stdlib, Java 21, sh = bash `set -euo pipefail`.

## Layout

- `bin/`: orchestrators: `init.sh` (one command from zero to a working
  instance), `doctor.sh` (wiring doctor), `smoke-loop.sh` (full-loop smoke),
  `kit-status.sh` (the kit README's measured status block),
  `fetch-tools.sh`, `metrics.sh`, `cartography.sh`, `clean-pass.sh`,
  `verify-commit.sh`, `verify-sectors.sh`, `benchmark-release.sh`,
  `install.sh` (picks the runtimes), `install-claude.sh`, `install-pi.sh`
  (reads the skill list out of `install-claude.sh`), `sync-instance.sh`,
  `adopt.sh`.
- `mcp/`: `metodo` MCP server (JSON-RPC over stdio, stdlib): `catalog.py` is
  the tool table; each one wraps a script from `lib/` or `bin/`.
- `hooks/`: Claude Code hooks (path and gate guards, budget, output
  validation, session state, ledger); `hooks.settings.json` is what the
  installer merges into `.claude/settings.local.json`.
- `lib/`: one module per tool; `baseline.py` (I/O), `repo_scan.py` and
  `toolenv.py` are the common base; `worktree.sh` is the only lib in bash.
  `base_ref.py` is the one resolver of the repo's base ref (explicit, config
  `test_sectors.base_ref`, `origin/HEAD`, then `origin/develop`);
  `detect_repo.py` reads a target repo's facts for `adopt.sh` and
  `init.sh`; `suggest.py` detects the optional helpers; `init_kit.py`,
  `doctor.py` and `smoke_loop.py` hold the logic of the three wrappers.
- `config/`: `project.json` is the only file a new project fills in
  (docs_root, shared_build_files, critical_paths, property_order,
  invariant_prefix, language); the rest of `config/*.json` ships a minimal
  generic placeholder, with its full instance over a critical-flow domain in
  `config/examples/critical-flow/`. `config/suggestions.json` is the data
  `suggest.py` reads: each helper, its detect rule and its exact command.
- `schemas/`: informal descriptions (change-card, role-contract), the round
  schemas (findings, blindspots, claims, verdict, brief, handoff), the
  receipt (`receipt`) and each role's output (`verification`, `*-output`).
- `baselines/`, `out/`, `vendor/`: generated, gitignored.
- `tests/`: one `unittest` per `lib/` module, with a negative control.

## Invocation

```bash
bin/init.sh <repo> [--instance D] [--audit D] [--runtime claude|pi|all] [--answers <json|file>]
            [--engram-project NAME] [--no-fetch] [--no-baseline] [--no-smoke]
            [--read-global-config] [--dry-run]  # report: <instance>/out/init/<repo_sha>.json
bin/init.sh <repo> --uninstall [--instance D] [--audit D] [--purge] [--runtime claude|pi|all] [--dry-run]
                                         # unplug: report <instance>/out/uninstall/<repo_sha>.json; instance and
                                         # audit stay; --purge deletes them only if untouched; exit 1 = kit left
bin/doctor.sh <repo> [--tools D] [--runtime claude|pi|all] [--out F]   # FAIL names its fix
bin/doctor.sh <repo> --absent [--runtime claude|pi|all]   # after --uninstall: PASS = nothing left, kit_absent
bin/smoke-loop.sh <repo> [--tools D] [--keep] [--out F]   # card -> receipt -> finalize, throwaway clone
bin/kit-status.sh --check | --write [--allow-failing]   # README status block: --check is cheap (exit 1 =
                                         # stale, prints the fix); --write runs the suite + init on a fixture
bin/adopt.sh <repo> <audit-folder> [--critical-flow-example] [--answers <json|file>] [--dry-run]
             [--allow-kit] [--kit D]   # writes config/project.json; refuses on the kit unless --allow-kit
bin/install.sh <repo> [--runtime claude|pi|all] [--tools D] [--engram-project NAME]
bin/install.sh <repo> --uninstall [--runtime claude|pi|all] [--tools D]   # removes only byte-identical kit
                                         # files; a modified one is kept and printed `kept: modified`
bin/install-claude.sh <repo> [--tools D] [--uninstall] # agents, skills, .mcp.json, hooks
bin/install-pi.sh <repo> [--tools D] [--uninstall]     # .pi/agents, .pi/skills, .pi/mcp.json, guards extension
bin/sync-instance.sh <instance>          # code to an instance; config/ only what is missing; personal assets never
python3 lib/suggest.py <repo> [--tools D] [--runtime claude|pi|all] [--read-global-config]   # never installs
python3 lib/detect_repo.py <repo>        # language, build files, base ref, ticket keys (JSON)
python3 lib/base_ref.py <repo> [--config project.json] [--base REF]
python3 mcp/server.py --selftest         # initialize + tools/list in-process
python3 lib/rdd_receipt.py status --repo <repo>   # start | capture | finalize | acknowledge | validate
python3 lib/rdd_risk.py --repo <repo> --base origin/develop [--change-card F]
python3 lib/test_sectors.py <repo> [--base B] [--check-verify <repo>/tools/verify/verify.sh]
bin/verify-sectors.sh <repo> [--base B] [--tasks a,b]  # sector battery under the Gradle lock
python3 lib/hooks_report.py              # ledger figures and the warn -> block criterion
python3 lib/hooks_report.py --verdicts --as-of YYYY-MM-DD [--transcript-metrics F] [--format md]
                                         # per-element PROMOTE|DEMOTE|KEEP|EXPIRE; never writes config
bin/mark-fp.sh <session> <seq> --reason "..."   # owner false-positive mark; the ledger is never edited
bin/fetch-tools.sh                       # detekt, PMD, ktlint -> vendor/
python3 lib/shape_metrics.py <repo> [--modules a,b]
python3 lib/duplication_cpd.py <repo> --calibrate     # fixes config/cpd.json (deliberate change)
python3 lib/duplication_cpd.py <repo> [--min-tokens N] [--files a.kt,b.kt]
python3 lib/dep_boundaries.py <repo> [--config config/dep-boundaries.json]
python3 lib/domain_invariants.py <repo> [--config config/invariants-checks.json]
python3 lib/role_contract_validator.py --contract <c>.contract.json --repo <r> (--range A..B | --worktree D)
python3 lib/findings_schema_validator.py <json> --schema schemas/<name>.schema.json
python3 lib/change_card_validator.py [--extract] <file|->
python3 lib/brief_check.py <brief.md>    # goal-contract fields, S# references, BUDGET number; exit 1 on FAIL
python3 lib/docs_lint.py config/docs-caps.json [--tokens config/token-caps.json] [--root DIR]
                                         # line caps; --tokens adds ceil(chars/4) caps; --root .. lints this checkout
bin/route.sh <task.json> --as-of YYYY-MM-DD [--log [PATH]]   # roster: role, model, effort, when (JSON)
python3 lib/router_eval.py [--fixtures DIR] [--out FILE]       # router vs tests/fixtures/router; exit 1 on a miss
bin/metrics.sh <repo> [--save]           # shape_metrics + duplication_cpd + delta vs baselines/latest;
                                         # --save: baseline for the sha (clean tree only)
bin/cartography.sh <repo>                # + hotspots (90d) + merge-tree vs the integration branch
bin/clean-pass.sh <repo>                 # union of flagged rows, proposes nothing
bin/verify-commit.sh <repo> <range> [--full]     # tools/verify/verify.sh per commit, in a worktree
bin/benchmark-release.sh <repo> <refA> <refB> [--force-recompute]
bin/run-check.sh <name> [--runs-dir DIR] [--cwd DIR] -- <command...>   # runs a check, exit code passes through;
                                         # one line in out/runs/runs.jsonl: the only "green" proof the done gate accepts
python3 lib/done_check.py --repo <repo> --reply <file|-> [--task F] [--card F] [--tier T] [--waivers F] [--format block]
                                         # DONE-01..17 + a DONE-GATE: block to paste verbatim; exit 1 on BLOCK (MCP done_check)
bin/done-waive.sh DONE-xx --reason "..." [--session S] [--repo R]   # owner waiver into the session ledger, bound to
                                         # the current worktree (dies on any edit); an agent running it is asked or denied
python3 lib/activation.py --tier T [--task-kind K] [--runtime claude|pi] [--caller main|subagent] [--offline]
                          [--session S]   # profile bare|light|scripts|standard|full + element modes (JSON)
python3 -m unittest discover tests
```

## Activation profiles

`lib/activation.py` picks a profile from facts (first match: P0 RDD off → bare; P1 tier high, critical or
release → full; P2 medium → standard; P3 low → scripts; P4 exempt or exploring → light; P5 unknown →
standard) and reads each element's mode (OFF, LOG, WARN, BLOCK) from `config/activation.json`. The
absolute set (subagent build-file and `.claude/` edits, force push, subagent delivery, the budget deny,
the main-session build-file ask) is BLOCK in every profile; the loader refuses a config that lowers it.
With `activation.json` beside `project.json`, `hooks/_common.hook_mode` takes the profile from the
current receipt's tier; `rdd.hook_modes` still wins, and without a receipt tier `rdd.mode` decides. The
profile never falls within a session (`out/hooks/<session>/profile.json`). Without `activation.json`
the hook modes are exactly the old rule. Method: `odd/research/context/activation.md` §3.

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
