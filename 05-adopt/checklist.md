# Instantiating the kit in a project · checklist

Order matters: no change cards or rounds until a measured baseline exists. Typical time: an afternoon.

## 1. Declare (config/project.json, `03-tools/bin/adopt.sh <repo> <audit-folder>`)

- [ ] `property_order`: the hierarchy of what's protected, in tie-break order (8 properties is a good cap).
- [ ] `critical_properties`: the ones that require an invariant in the card and large-model adversaries.
- [ ] `shared_build_files`: build files that collide between branches (always off-limits to agents).
- [ ] `money_paths`: critical-flow paths (the path outranks the card's declaration); `rdd` (enabled, mode
      warn, exempt_globs, lens_paths) and `test_sectors` (path -> module Gradle tasks map).
- [ ] `docs_root` and `docs-caps.json`: which base documents have a cap and what it is.
- [ ] `invariant_prefix` and `invariants-checks.json`: which presence checks the script runs.
- [ ] `dep-boundaries.json`: nodes (modules or packages) and allowed or forbidden edges.
- [ ] Project vocabulary: one word per concept (what the terminal is called, the server, the vendor).

## 2. Write (the project's audit folder)

- [ ] `invariants.md`: INV-01..NN with today's guarantee mechanism (test / guard / script / none),
      `file:line@sha`, tag, and gap. Whatever has no guarantee is a finding, not philosophy.
- [ ] `CONVENTIONS.md` in the repo (committed): the language's official base + deltas with a stable ID and
      a detector.
- [ ] A copy of `CONTEXT-PACK.md` with a paragraph on "how this applies here" (paths, names, owner).

## 3. Tools

- [ ] `03-tools/bin/fetch-tools.sh` (jars pinned by sha256; no package managers).
- [ ] First run: `bin/metrics.sh <repo>` twice, empty `diff`; save the baseline for the clean sha.
- [ ] Calibrate the duplication threshold once (`duplication_cpd.py --calibrate`) and fix it in config.
- [ ] `bin/cartography.sh <repo>`: the first map; review by hand the boundary config it proposes.
- [ ] `bin/install.sh <repo> --runtime all [--tools <instance>] [--engram-project <name>]`: installs the
      same source into every runtime. For Claude Code that is agents, skills, `.mcp.json` (excluded from
      commits) and the hooks in `.claude/settings.local.json`; for pi (`--runtime pi`) it is `.pi/agents`,
      `.pi/skills`, the `.pi/mcp.json` prefix override and the guards extension. Both check that the sector
      map exists in the repo's `verify.sh` and smoke-test the MCP server. See
      `00-principles/runtime-adapters.md` for what each runtime does and does not enforce.

## 4. People and gates

- [ ] Owner: who decides, and at which gates. Emergency lane: what gets compressed and who signs off.
- [ ] What an agent does when the owner isn't available (wait, delegate, wait cap).
- [ ] Custody of the tools repo: remote, copy, which paths can never leave.
- [ ] A real environment, one session: where who holds it is written down.

## 5. Start

- [ ] First change card validated by script, with the lane the validator returns.
- [ ] First round of two adversaries with facts from scripts; minutes with the template.
- [ ] First benchmark: last shipped tag against the candidate; `not_measured` filled in with how to get it.
- [ ] Owner's review of the rule → property map, row by row (born Assumed).
