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

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| C1 | S1, S2 | worker (research: context engineering, main + subagents) | todo | `odd/research/context/context-engineering.md` |
| C2 | S1, S3 | worker (research: Engram as queryable memory) | todo | `odd/research/context/engram.md` |
| C3 | S1, S4 | worker (research: deterministic activation of kit elements) | todo | `odd/research/context/activation.md` |
| C4 | S1, S5 | worker (research: strict done gate) | todo | `odd/research/context/done-gate.md` |
| C6 | S6 | worker (measured audit of the kit's own texts) | todo | `odd/research/context/text-audit.md` |
| C5 | S1-S6 | inline synthesis | todo | method + owner decisions |

## Log

- **L1** (user, 2026-10-18, verbatim): "necesitio que lances agentes para hacer una investigacion /deepresearch, de como optimizar el uso de contexto algo actualziado par ahoy 18 oct 2026  donde se peuda ver realemnte, como optimizar los subagentes y la  conversacion principal a nivel de agentes y sacar potencialidad opcional en coo usar ENgram como ayuda aqui. para ahcer consultas. y que esta metodologia de trabajo de forma determinista permita ver cuando activar o desactivar los elementos, hooks, agentes, reglas, linterns,etc y me gustaria tambien una seccion estricta de lintern que permita levantar un flag antes de dar algo como hecho"
- **L2** (decision, coordinator): no `/deepresearch` skill exists in this harness; four parallel research lanes, each fetching official/primary sources into its own temp dir and writing one dossier; research only, no code in this step.
- **L3** (user, 2026-10-18, verbatim): "sobre lasrecuerda que todo el proyecto debe ser evaluado tambien para todo el tema de contexto y si los textos que estamos usando van optimos para eso,". Added S6 and C6.
