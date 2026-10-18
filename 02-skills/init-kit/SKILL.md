---
name: init-kit
description: Initializes the kit in a target repo with bin/init.sh (instance, install, baseline, doctor, smoke) after interviewing the owner for --answers; relays the report. Use it to start, re-check or unplug the kit in a repo.
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

`<repo>`: a git repository with at least one commit; optional flags as in step 3 (defaults: `~/<repo_name>-tools`, `~/<repo_name>-audit`, runtime `all`). Commands run from the kit's `03-tools/`.

## Steps

1. **Plan.** Run `bin/init.sh <repo> --dry-run` (writes nothing) and show the planned steps and any `preflight warnings` as printed. Exit 2: relay the message and stop.
2. **Interview.** At least four rounds of questions (`00-principles/methodology.md` §4), collecting only what `--answers` accepts: `property_order`, `critical_properties`, `critical_paths`, `ticket_keys` (lists of strings) and `language` (a string). Propose detected values first, quoted as printed by `python3 lib/detect_repo.py <repo>` (read-only); the hierarchy, critical properties and critical paths are not detected, so ask. A key left out stays with detection and returns as a pending human step. End by asking whether they want more questions or to start.
3. **Ask before writing.** Show the exact command with the flags agreed and wait for the owner's OK. Then run `bin/init.sh <repo> --answers '<json>' [--instance <dir>] [--audit <dir>] [--runtime claude|pi|all] [--engram-project NAME] [--no-fetch] [--no-baseline] [--no-smoke] [--read-global-config]`. `--answers` also takes a JSON file.
4. **Relay the report.** Read `<instance>/out/init/<repo_sha>.json` (the stderr summary prints its path) and relay, verbatim:
   - every entry of `steps` whose `status` is not `done`, with its `detail` and `fix`;
   - `pending_human_steps` grouped by `section` (`1. Declare` … `5. Start`), each with its `file`;
   - `suggestions`: each `missing` or `unknown` entry with its `why` and its exact `command`. Never run a suggestion's command yourself: installing a helper is the owner's call;
   - `doctor.verdict`, `doctor.kit_installed`, `smoke.verdict`, `smoke.loop_ran` and `ready_for_benchmark`.
5. **Doctor or smoke FAIL.** Relay each failing check's `fix` (doctor) or failing scenario (smoke) from `doctor.report` / `smoke.report` exactly as written; never improvise one. After the owner applies it, rerun step 3 (idempotent).

## Unplug

When the owner asks to remove the kit, run `bin/init.sh <repo> --uninstall --dry-run` first and relay its plan; run `bin/init.sh <repo> --uninstall` only after the owner's OK. Relay `removed`, `kept_modified`, `kept_in_use`, `kit_absent` and `instance`/`audit` from the report as printed: the skill relays, the owner decides. Add `--purge` only with the owner's explicit OK to delete the instance and the audit folder, and relay every refusal reason verbatim; never delete anything by hand on its behalf.

## Privacy and scope

- Global configs are read only with `--read-global-config` after the owner opts in, to test one MCP server key; contents are never printed or stored.
- Nothing global is installed and personal assets are never copied. Writes go only to the instance, the audit folder and the repo's local kit files (`.claude/agents` and `.claude/skills` show as untracked until the owner ignores or commits them).

## What the model may add

The interview questions and the grouping of the report. Never an unconfirmed `--answers` value, a status, count or path the report lacks, or a fix the doctor or smoke did not print.

## Output

The instance, the audit-folder scaffolds, the kit installed in `<repo>`, the reports under `<instance>/out/{init,doctor,smoke}/`, and a relay of what is left to the owner.

## Escalate to the owner

- Before any run without `--dry-run`, and before `--read-global-config`.
- A doctor or smoke `fix` touches a shared build file or global state.
- `ready_for_benchmark` is false for a repo meant as an `08-benchmark` kit arm.
- `pending_human_steps` in `4. People and gates`: only the owner can decide them.
