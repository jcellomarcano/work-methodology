# Feature: context-optimization

**Objective.** Research, current as of 2026-10-18, how to optimize context use in the main conversation and in subagents, what Engram can optionally add as a queryable memory, a deterministic policy that says when each kit element (hooks, agents, rules, linters, skills, memory) is on or off, and a strict "done" linter that raises a flag before anything is reported as done.
**Branch.** `feat/harness-guides` worktree `model-router` (research files only under `odd/research/context/`); implementation lands later in its own branch.

## Specs

Quoted fragments are the user's exact words (Spanish, 2026-10-18); the requirement text is English.

- **S1 Deep research, current.** "necesitio que lances agentes para hacer una investigacion /deepresearch, de como optimizar el uso de contexto algo actualziado par ahoy 18 oct 2026 donde se peuda ver realemnte". Sourced research (fetched pages, read date 2026-10-18, verbatim quotes checked by script), with measured numbers where they exist.
- **S2 Main conversation and subagents.** "como optimizar los subagentes y la conversacion principal a nivel de agentes". Concrete techniques for both levels, with their evidence and cost.
- **S3 Engram, optional.** "sacar potencialidad opcional en coo usar ENgram como ayuda aqui. para ahcer consultas". How Engram can be queried to save context, when it helps and when it does not, as an optional component.
- **S4 Deterministic activation.** "que esta metodologia de trabajo de forma determinista permita ver cuando activar o desactivar los elementos, hooks, agentes, reglas, linterns,etc". A decision table computable without an LLM that says which elements are on or off for a given task.
- **S5 Strict done linter.** "me gustaria tambien una seccion estricta de lintern que permita levantar un flag antes de dar algo como hecho". A deterministic gate that refuses "done" while required evidence is missing.

- **S6 Whole-project text audit.** "recuerda que todo el proyecto debe ser evaluado tambien para todo el tema de contexto y si los textos que estamos usando van optimos para eso". Every text the kit puts into an agent's context (AGENTS.md, CLAUDE.md, CONTEXT-PACK.md, agent bodies and contracts, skill files, rendered pi agents, hook messages, MCP tool descriptions and schemas, identity block, principles the agents are told to read) is measured for size and load mode (always / on demand / never), duplication across files, and fitness for context, with concrete trims.

- **S7 Balance and goal anchoring.** "de que manera podemos balancear que el uso de contexto de los subagentes sea optimo para no bajar la calidad de las respeustas? y siempre tener el target y objetivo claro. DE esa manera no gastar demasiado, pero si trabajar en la direccion correcta". Subagent context is sized per role and tier without starving evidence, every brief carries a verifiable goal tied to the S# it serves, and drift and over- or under-spending are measured deterministically.

- **S8 Fix the text-audit findings now.** "necesito que estos sean resultos": the five problems of `text-audit.md` (duplicated boilerplate in the 11 agent bodies and doubled on pi; Spanish leftovers in model-facing text; `../../` pointers that break after install; the cold-start pack never delivered to subagents; no size cap on agents, skills and templates) and the top trims (AGENTS.md reads only the README status block; dedupe agent bodies; cap skill descriptions), never cutting safety rules, the evidence rule or the personal-files rule.

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| C1 | S1, S2 | worker (research: context engineering, main + subagents) | todo | `odd/research/context/context-engineering.md` |
| C2 | S1, S3 | worker (research: Engram as queryable memory) | todo | `odd/research/context/engram.md` |
| C3 | S1, S4 | worker (research: deterministic activation of kit elements) | todo | `odd/research/context/activation.md` |
| C4 | S1, S5 | worker (research: strict done gate) | todo | `odd/research/context/done-gate.md` |
| C6 | S6 | worker (measured audit of the kit's own texts) | todo | `odd/research/context/text-audit.md` |
| C7 | S8 | worker A, test-first | done | agent bodies: dedupe, English, installable pointers, cold-start core delivered, pi single copy |
| C8 | S8 | worker B, test-first | done | token caps in docs_lint (`config/token-caps.json`), skill description cap, AGENTS.md trim, `--root` for docs_lint |
| C5 | S1-S7 | inline synthesis | todo | method + owner decisions |

## Log

- **L1** (user, 2026-10-18, verbatim): "necesitio que lances agentes para hacer una investigacion /deepresearch, de como optimizar el uso de contexto algo actualziado par ahoy 18 oct 2026  donde se peuda ver realemnte, como optimizar los subagentes y la  conversacion principal a nivel de agentes y sacar potencialidad opcional en coo usar ENgram como ayuda aqui. para ahcer consultas. y que esta metodologia de trabajo de forma determinista permita ver cuando activar o desactivar los elementos, hooks, agentes, reglas, linterns,etc y me gustaria tambien una seccion estricta de lintern que permita levantar un flag antes de dar algo como hecho"
- **L2** (decision, coordinator): no `/deepresearch` skill exists in this harness; four parallel research lanes, each fetching official/primary sources into its own temp dir and writing one dossier; research only, no code in this step.
- **L3** (user, 2026-10-18, verbatim): "sobre lasrecuerda que todo el proyecto debe ser evaluado tambien para todo el tema de contexto y si los textos que estamos usando van optimos para eso,". Added S6 and C6.
- **L4** (user, 2026-10-18, verbatim): "ahora de que manera podemos balancear que el uso de contexto de los subagentes sea optimo para no bajar la calidad de las respeustas? y siempre tener el target y objetivo claro. DE esa manera no gastar demasiado, pero si trabajar en la direccion correcta". Added S7; C5 worker steered to include a balance and goal-anchoring section.
- **L5** (user, 2026-10-18): "necesito que estos sean resultos" quoting the five text-audit problems and the top trims. Added S8; C7 and C8 run in parallel with disjoint files (token caps go to a new `03-tools/config/token-caps.json` so they do not collide with H4 editing `docs-caps.json`).
- **L6** (user, 2026-10-18, answers): done gate "Aviso visible, después bloquea (recomendado)" (D2); reply_lint "Apagar el hook, dejar la skill (recomendado)" (D3); Engram "Encendido con regla de lectura (recomendado)" (D4); the rest "Tomá tus recomendaciones": D1 orchestrator auto-compact window 300k, D5 skill description cap 60 tokens, D6 six manual-only skills, D7 cold-start core = CONTEXT-PACK head + §4 (~236 tokens), D8 Codex/Antigravity/OpenCode declared unguarded now and hooks ported one harness at a time, D9 subagent report cap 2,000 tokens, D10 `omitClaudeMd` for roles with a contract (with a no-rule-lost test), D11 Google thresholds 0.90 precision / 0.10 act rate / 20 fires / 7 days, D12 provisional budgets small 30k / medium 60k / large 120k moved only by the §4 rule.
- **L7** (evidence, C8): token caps in `docs_lint` (`--tokens config/token-caps.json --root`), 14 skill descriptions cut to ≤ 60 tokens, AGENTS.md 739 → 590 tokens; RED 3F/14E → GREEN 38 OK. Offenders left for C7/follow-up: comment-gate body 1376 > 900, init-kit body 1232 > 1000, receipt-review body 1013 > 1000, CONTEXT-PACK 1963 > 1800.
- **L8** (evidence, C7 + C8 + coordinator trims): agent bodies deduped (10 of 11 ≤ 800 tokens), English tags, no `../` in installed agents, a 240-token subagent core rendered from CONTEXT-PACK into every agent (RED 33F/5E → GREEN 119 OK). Token caps in `docs_lint` with a documented per-file override (comment-gate 1100 for its pinned DOC/ISO rulebook; RED 2F → GREEN 23 OK); init-kit, receipt-review and CONTEXT-PACK trimmed under their caps; `docs_lint --tokens --root ..` exit 0.
