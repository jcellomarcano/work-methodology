---
name: init-kit
description: Initializes the whole kit in a target repo with bin/init.sh (instance, adaptation, scaffolds, pinned tools, install, baseline, map, wiring doctor, full-loop smoke, helper suggestions) and conducts the owner interview whose answers the script takes through --answers. The script initializes and reports; the model interviews and relays the report. Use it to start the kit in a new repo or to re-check one where it is already installed.
version: 1.0.0
triggers:
  - initialize the kit
  - install the kit in this repo
  - set up the methodology here
  - start the kit in a new project
  - is the kit ready for the benchmark
  - unplug the kit from this repo
allowed-tools: [Read, Bash]
---

**IRON LAW**: the script initializes, the model interviews. No number, status or path goes to the owner unless `init.sh`, the doctor or the smoke printed it. Nothing runs that writes before the owner says yes.

## Input

`<repo>`: a git repository with at least one commit. Optional: `--instance <dir>` (default `~/<repo_name>-tools`), `--audit <dir>` (default `~/<repo_name>-audit`), `--runtime claude|pi|all` (default `all`), `--engram-project NAME`. Every command below runs from the kit's `03-tools/`.

## Steps

1. **Plan.** Run `bin/init.sh <repo> --dry-run` (writes nothing). Show the owner the planned steps and any `preflight warnings` exactly as printed. Exit 2 is a usage or preflight error: relay its message and stop.
2. **Interview.** At least four rounds of questions (`00-principles/methodology.md` §4), collecting only what `--answers` accepts: `property_order` (the hierarchy of what is protected, in tie-break order), `critical_properties` (those that require an invariant in the card and large-model adversaries), `critical_paths` (critical-flow paths), `ticket_keys` (these four are lists of strings) and `language` (a string). Propose the detected values first: `python3 lib/detect_repo.py <repo>` (read-only) prints `primary_language`, `ticket_keys`, `shared_build_files` and `base_ref`; quote them as printed. The hierarchy, the critical properties and the critical paths are not detected: ask for them. The owner confirms, corrects or leaves a key out. A key left out stays with detection and comes back as a pending human step. End by asking whether they want more questions or to start.
3. **Ask before writing.** Show the exact command with the flags agreed and wait for the owner's OK. Then run `bin/init.sh <repo> --answers '<json>' [--instance <dir>] [--audit <dir>] [--runtime claude|pi|all] [--engram-project NAME] [--no-fetch] [--no-baseline] [--no-smoke] [--read-global-config]`. `--answers` also takes a JSON file.
4. **Relay the report.** Read `<instance>/out/init/<repo_sha>.json` (the stderr summary prints its path) and relay, verbatim:
   - every entry of `steps` whose `status` is not `done`, with its `detail` and `fix`;
   - `pending_human_steps` grouped by `section` (`1. Declare` … `5. Start`), each with its `file`;
   - `suggestions`: each `missing` or `unknown` entry with its `why` and its exact `command`. Never run a suggestion's command yourself: installing a helper is the owner's call;
   - `doctor.verdict`, `doctor.kit_installed`, `smoke.verdict`, `smoke.loop_ran` and `ready_for_benchmark`.
5. **Doctor or smoke FAIL.** Read the report `doctor.report` / `smoke.report` points to and relay the `fix` of each failing check (doctor) or the failing scenario (smoke) exactly as written. Never improvise a fix. After the owner applies it, rerun step 3: the report is idempotent over an unchanged repo.

## Unplug

When the owner asks to remove the kit, run `bin/init.sh <repo> --uninstall --dry-run` first and relay its plan; run `bin/init.sh <repo> --uninstall` only after the owner's OK. Relay `removed`, `kept_modified`, `kept_in_use`, `kit_absent` and `instance`/`audit` from the report as printed: the skill relays, the owner decides. Add `--purge` only with the owner's explicit OK to delete the instance and the audit folder, and relay every refusal reason verbatim; never delete anything by hand on its behalf.

## Privacy and scope

- Global configs (`~/.claude.json`, `~/.pi/agent/mcp.json`) are read only with `--read-global-config`, and only after the owner opts in: read-only, to test whether one MCP server key is present; their contents are never printed or stored.
- The skill and the script never install anything global and never copy the owner's personal assets (the sync excludes them). They write only the instance, the audit folder and the repo's local kit files: `.mcp.json` and the pi files are git-excluded; `.claude/agents` and `.claude/skills` show as untracked until the owner ignores or commits them.

## What the model may add

The interview questions and the grouping of the report for the owner. Never a value for `--answers` the owner did not confirm, never a status, count or path the report does not carry, never a fix the doctor or the smoke did not print.

## Output

The instance at `--instance`, the audit-folder scaffolds (`invariants.md`, `CONTEXT-PACK.md`, `CONVENTIONS.md.template`), the kit installed in `<repo>`, the reports under `<instance>/out/{init,doctor,smoke}/<repo_sha>.json`, and a relay of what is left to the owner.

## Escalate to the owner

- Before any run without `--dry-run`, and before `--read-global-config`.
- The doctor or the smoke FAILs and its `fix` touches a shared build file or global state.
- `ready_for_benchmark` is false and the repo is meant for a kit arm of `08-benchmark`: the arm is not valid until it is true.
- `pending_human_steps` in `4. People and gates`: only the owner can decide them.
