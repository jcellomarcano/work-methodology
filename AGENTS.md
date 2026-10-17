# AGENTS.md · how an agent enters this repo

This repo is a portable working-methodology kit for software built with AI agents. It is the source of
truth: roles, skills, scripts, hooks and rules live here once and get rendered into target repos.

## Read first, in this order

1. `CONTEXT-PACK.md`: the whole methodology in ≤ 120 lines. Read nothing else until a task needs it.
2. `README.md`: the kit map and the measured status block (written by a script, never by hand).
3. `00-principles/methodology.md`: the operating law, when a task touches the rules themselves.
4. The task document under `odd/tasks/`, if the work continues a tracked feature.

## Plug, check, unplug (on a target repo, never on this kit)

- Plug: `03-tools/bin/init.sh <repo> --dry-run`, then without `--dry-run`. It syncs the tools instance,
  adapts it, installs for Claude Code and pi, saves a baseline, runs the doctor and the smoke, and
  lists the steps only a human can do. The `init-kit` skill interviews the owner and calls it.
- Check: `03-tools/bin/doctor.sh <repo> --tools <instance>` (wiring) and `03-tools/bin/smoke-loop.sh
  <repo>` (the receipt loop end to end on a throwaway clone).
- Unplug: `03-tools/bin/init.sh <repo> --uninstall`; it removes only what the kit installed and keeps
  the instance and audit folder unless `--purge` is given with the owner's OK.

## Rules when changing this kit

- Evidence or silence: every claim cites `file:line@sha`, a commit, or pasted output, with a tag
  (Measured, Tested, Inferred, Assumed, Unknown).
- Test-first for behavior: `cd 03-tools && METODO_MEMORY=off python3 -m unittest discover tests`.
- Every document has a line cap: `cd 03-tools && python3 lib/docs_lint.py config/docs-caps.json`.
- An important change lands with the README status block re-measured in the same commit:
  `03-tools/bin/kit-status.sh --write`, then `03-tools/bin/kit-status.sh --check` (a drift test fails
  the suite otherwise).
- Artifacts (code, docs, commits) are in English; talk to the owner in the owner's language.
- Push, PR, merge, tags, shared build files and anything outside the repo are the owner's decision.
- Never read, copy, install or stage personal files: any path matching `*.personal.*` or under a
  `personal/` folder (both git-ignored), and `07-communication/bench/tmp/`.

## Where things are

| Need | Go to |
|---|---|
| a role (agent) and its contract | `01-roles/agents/` |
| a skill | `02-skills/` |
| a script, hook, MCP tool, schema | `03-tools/` (`03-tools/README.md`) |
| a template | `04-templates/` |
| instantiation reference | `05-adopt/checklist.md` |
| language rules | `06-languages/` |
| how to talk to a person | `07-communication/` |
| kit vs vanilla measurements | `08-benchmark/` |
