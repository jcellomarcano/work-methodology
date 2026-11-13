# Feature: team-adoption

**Objective.** A team lead can read two pages and know how to adopt the kit in steps, how to decide with numbers whether it is good for the team, and where the kit stands against what the market already ships.
**Branch.** On the chain, after the benchmark port (`feat/benchmark-port`, worktree `~/work-methodology-worktrees/benchmark-port`); the owner asked for one branch merged into `main` (L3). Delivery `ask-on-risk`; documents only, forecast under 400 authored lines. Runners: `python3 03-tools/lib/docs_lint.py 03-tools/config/docs-caps.json --tokens 03-tools/config/token-caps.json`; `cd 03-tools && METODO_MEMORY=off python3 -m unittest tests.test_docs_lint tests.test_english_artifacts tests.test_entry_points`. Risk: none beyond the documents (passive content; a wrong command in a guide is caught by S6).

## Specs

- **S1 Request (owner, verbatim, from the goal).** "quiero que se peuda presentar como una metodologia de trabajo para equipos que peudan adopatarla y medir si realmente es buena o no" and "que resalte donde es pionera en el mercado, e integre lo que otro ya hacen mejor como lead top".
- **S2 Adoption in steps.** `docs/07-adoption.md` carries the five steps of the audit (`odd/research/kit-audit-2026-11/audit.md` section 8): rules only; wired in warn mode; calibrate; block what earned it; the full loop on critical paths. Each step says when, who does it, the exact commands of this tree, and an exit check that is a command's output or a file, never an opinion. It says how to back out (`init.sh --uninstall`) and what stays after it. What the page already says and still holds is kept.
- **S3 Measurement runbook.** One page, `docs/09-measurement.md`, answers "is it good for us?": what is compared (two ways of working, both with agents); the baseline the kit records by itself (the adoption record, the stored session rows, the phase 1 report); the A/B protocol with its commands (`bench.py ab`, `judge`, `report`; at least three repetitions; named arms; one model and effort); the headline metrics and where each number comes from; the decision rule (non-inferiority, an interval that crosses zero is "not shown", n beside every comparison, a single run is a signal); what a run costs and that the owner approves the spend; and what cannot be measured yet. Every statement carries its tag.
- **S4 Market position.** One short page, `docs/10-position.md`: what is rare or unclaimed in the kit, what others already claim (credited by name), what is commodity, and what the leaders do better, each with its source in `odd/research/` and its tag. No novelty is claimed where the research found a prior holder, and absence in other frameworks is stated as read from their READMEs, not audited.
- **S5 Entry points.** `README.md` links the two new pages from its reading table (never inside the status block), `docs/07-adoption.md` links the runbook, and both new pages have a line cap and a token cap in the config files.
- **S6 Rules.** Every command, script path, flag and file named in the three pages exists in this tree, checked by reading the code and by a test that fails when a page names a script path that is not in the tree. Numbers come from a file in the repo with its path; nothing is measured anew and no benchmark is run. Artifacts in English; no line cap raised.
- **S7 Not in this feature.** Running the seeded-defect phase (the protocol forecasts USD 550 to 880; the owner's budget decision); publishing; the Codex installer.

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| T1 | S2 to S6 | delegated writer (owner preference: role agents do each task) | pending | |
| T2 | all | parent: seam check against the code, status block, close | pending | |

## Log

- **L1 (2026-11-13, owner, verbatim).** "tienes permiso a proceder u terminar todo hasta el /goal"; the request itself is the goal text quoted in S1.
- **L2 (2026-11-13, scope).** The audit names what a team still lacks to judge the kit: a one-page runbook and adoption steps with exit checks (audit sections 4 and 8). The statistics code, the repetitions and the two-order judges it also listed arrived with `feat/benchmark-port`; the seeded tasks and a paid run did not. [Measured: `odd/research/kit-audit-2026-11/audit.md`]
- **L3 (2026-11-13, owner, verbatim).** "sigue hasta terminar todo y lo mergeas a megain quedandote con 1 sola rama y la subes a psuh". Read as: finish, merge everything into `main`, keep one branch, push it. So this feature lands on the same chain instead of a branch of its own.

