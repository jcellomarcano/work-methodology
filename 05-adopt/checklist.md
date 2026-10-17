# Instantiating the kit in a project · checklist

Order matters: no change cards or rounds until a measured baseline exists. Typical time: an afternoon.

## 0. One command

```bash
03-tools/bin/init.sh <repo> --dry-run              # the plan; writes nothing
03-tools/bin/init.sh <repo> [--answers <json|file>] [--instance <dir>] [--audit <dir>] [--runtime claude|pi|all]
```

Or the `init-kit` skill: it interviews the owner for `--answers` (`property_order`,
`critical_properties`, `critical_paths`, `ticket_keys`, `language`) and calls the script. Defaults:
`--instance ~/<repo_name>-tools`, `--audit ~/<repo_name>-audit`. The report lands in
`<instance>/out/init/<repo_sha>.json`; every item below that init cannot do comes back in it under
`pending_human_steps`, with its section and file. Nothing is skipped silently.

`adopt.sh` run from the kit itself refuses (exit 2): init runs the instance's copy with `--kit`.

Marks: **[init]** done by `init.sh`; **[human]** a pending human step it prints; **[init + human]**
init writes a detected or answered value, the owner confirms it.

## 1. Declare (`<instance>/config/project.json`)

- [ ] [init + human] `property_order`: the hierarchy of what's protected, in tie-break order (8 is a good cap).
- [ ] [init + human] `critical_properties`: the ones that require an invariant in the card and large-model
      adversaries.
- [ ] [init] `shared_build_files`: detected build files that collide between branches (off-limits to agents).
- [ ] [init + human] `critical_paths`: critical-flow paths (the path outranks the card's declaration); `rdd`
      (enabled, mode warn, exempt_globs, `lens_paths` [human]) and `test_sectors` (`base_ref` detected;
      path -> module test tasks map [human]).
- [ ] [init] `docs_root` (the audit folder); [human] `docs-caps.json`: which base documents have a cap.
- [ ] [human] `invariant_prefix` and `invariants-checks.json`: which presence checks the script runs.
- [ ] [human] `dep-boundaries.json`: nodes (modules or packages) and allowed or forbidden edges.
- [ ] [human] Project vocabulary: one word per concept (what the device is called, the server, the vendor).

## 2. Write (the project's audit folder)

- [ ] [init + human] `invariants.md`: init writes the empty table; the owner fills INV-01..NN with today's
      guarantee mechanism (test / guard / script / none), `file:line@sha`, tag, and gap. Whatever has no
      guarantee is a finding, not philosophy.
- [ ] [init + human] `CONVENTIONS.md` in the repo (committed): init writes `CONVENTIONS.md.template` in the
      audit folder, pointing at the language digest; the owner fills the deltas (stable ID, detector) and
      commits it in the repo.
- [ ] [init + human] A copy of `CONTEXT-PACK.md` with a "how this applies here" section (paths, names,
      owner): init writes the copy, the owner writes the section.

## 3. Tools

- [ ] [init] Tools instance synced from the kit (`bin/sync-instance.sh`, personal assets excluded); a new
      one gets `git init` and one commit. [human] Commit the adapted config yourself.
- [ ] [init] `bin/fetch-tools.sh` (jars pinned by sha256; no package managers); skip with `--no-fetch`.
- [ ] [init] First baseline: `bin/metrics.sh <repo> --save` on a clean tree (refuses a dirty one); skip with
      `--no-baseline`. On a dirty tree or a non-Gradle repo it stays [human].
- [ ] [init] Calibrate the duplication threshold once (`duplication_cpd.py --calibrate`), when PMD is fetched
      and `duplication-targets.json` lists candidates; otherwise [human].
- [ ] [init] `bin/cartography.sh <repo>`: the first map; [human] review the boundary config it proposes.
- [ ] [init] `bin/install.sh <repo> --runtime all --tools <instance> [--engram-project <name>]`: installs the
      same source into every runtime. For Claude Code that is agents, skills, `.mcp.json` (excluded from
      commits) and the hooks in `.claude/settings.local.json`; for pi it is `.pi/agents`, `.pi/skills`,
      the `.pi/mcp.json` prefix override and the guards extension. [human] Trust the project in pi once.
      See `00-principles/runtime-adapters.md` for what each runtime does and does not enforce.
- [ ] [init] Wiring doctor (`bin/doctor.sh <repo> --tools <instance>`): a FAIL names its fix.
- [ ] [init] Full-loop smoke (`bin/smoke-loop.sh <repo>`) on a throwaway clone; skip with `--no-smoke`.
      `ready_for_benchmark` is true only when the doctor's `kit_installed` and the smoke's `loop_ran` are.
- [ ] [init] Helper suggestions (Engram, Context7, gentle-ai, gh, java, node) with the exact command for
      what is missing; nothing is installed. Global configs are read only with `--read-global-config`.

## 4. People and gates [human]

- [ ] Owner: who decides, and at which gates. Emergency lane: what gets compressed and who signs off.
- [ ] What an agent does when the owner isn't available (wait, delegate, wait cap).
- [ ] Custody of the tools repo: remote, copy, which paths can never leave.
- [ ] A real environment, one session: where who holds it is written down.

## 5. Start [human]

- [ ] First change card validated by script, with the lane the validator returns.
- [ ] First round of two adversaries with facts from scripts; minutes with the template.
- [ ] First benchmark: last shipped tag against the candidate; `not_measured` filled in with how to get it.
- [ ] Owner's review of the rule → property map, row by row (born Assumed).

## Unplug [human decides]

```bash
03-tools/bin/init.sh <repo> --uninstall --dry-run   # the plan, what is installed now; writes nothing
03-tools/bin/init.sh <repo> --uninstall [--purge]   # report: <instance>/out/uninstall/<repo_sha>.json
```

- Removes from the repo only what the kit installed and is still byte-identical to its render, for
  Claude Code and pi; a kit file you modified stays, listed in `kept_modified` (exit 1). Your own
  hooks, servers, agents, skills, permissions and exclude lines are never touched.
- The instance and the audit folder stay. `--purge` deletes them only when untouched: the instance with
  init's single commit and no change of yours (and the repo `kit_absent`), the audit folder with only
  init's scaffolds as written. Otherwise it refuses and lists why.
- `03-tools/bin/doctor.sh <repo> --absent` proves nothing is left: `kit_absent` true.
