# AGENTS.md · how an agent enters this repo

A portable working-methodology kit for software built with AI agents and its source of truth: roles,
skills, scripts, hooks and rules live here once and get rendered into target repos.

## Read first, in this order

1. `CONTEXT-PACK.md`: the whole methodology in ≤ 120 lines. Read nothing else until a task needs it.
2. `README.md`, only two sections: the status block ("Start here", written by a script) and "Repository map".
3. `00-principles/methodology.md`: the operating law, when a task touches the rules themselves.
4. The task document under `odd/tasks/`, if the work continues a tracked feature.

## Plug, check, unplug (on a target repo, never on this kit)

Plug with `03-tools/bin/init.sh <repo>` (`--dry-run` first, `--uninstall` to unplug); check and unplug
details are in README "Start here". Before any launch, `03-tools/bin/route.sh <task.json> --as-of <date>`
(MCP `route`) prints the roster; Fable 5.1 needs the owner's OK.

## Rules when changing this kit

- Evidence or silence: every claim cites `file:line@sha`, a commit, or pasted output, with a tag
  (Measured, Tested, Inferred, Assumed, Unknown).
- Test-first for behavior: `cd 03-tools && METODO_MEMORY=off python3 -m unittest discover tests`.
- Every document has a line and token cap; lint this checkout from the repo root:
  `python3 03-tools/lib/docs_lint.py 03-tools/config/docs-caps.json --tokens 03-tools/config/token-caps.json --root .`
- An important change re-measures the README status block in the same commit:
  `03-tools/bin/kit-status.sh --write`, then `--check` (a drift test fails the suite otherwise).
- Artifacts (code, docs, commits) are in English; talk to the owner in the owner's language.
- Push, PR, merge, tags, shared build files and anything outside the repo are the owner's decision.
- Never read, copy, install or stage personal files: any path matching `*.personal.*` or under a
  `personal/` folder (both git-ignored), and `07-communication/bench/tmp/`.

## Where things are

- Roles and their contracts `01-roles/agents/`; skills `02-skills/`; templates `04-templates/`.
- Scripts, hooks, MCP tools, schemas `03-tools/` (`03-tools/README.md`).
- Instantiation `05-adopt/checklist.md`; language rules `06-languages/`; talking to a person
  `07-communication/`; kit vs vanilla measurements `08-benchmark/`.
