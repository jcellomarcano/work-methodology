# Feature: model-router

**Objective.** Research the latest models and effort controls (Claude, Gemini, GPT, local open-source) and turn them into a routing method for launching multi-agent work (which model, which effort, when), plus a deterministic script that decides the roster for a task and evaluates routing decisions.
**Branch.** `feat/model-router` in worktree `metodologia-de-trabajo-worktrees/model-router`, from the public English tree 57b69cf; rebased onto `port/update` before any code change (the port renames the kit to English paths). Research dossiers land first and touch no existing file.
**Tests.** `cd 03-tools && METODO_MEMORY=off python3 -m unittest discover tests`; docs caps with `python3 lib/docs_lint.py config/docs-caps.json`; README block with `bin/kit-status.sh --check`.

## Specs

Quoted fragments are the user's exact words (Spanish, 2026-10-16); the requirement text is English.

- **S1 Work on routing.** "necesito que se trabaje en el routing". The kit's routing stops being static frontmatter that no code reads (`08-benchmark/reports/phase1-findings.md` §6: `model-tiers.json` is read by no code, no effort is set, no routing log).
- **S2 Deep research.** "haz un /deepresearch donde se haga la investigacion referente a como hacer un router referente a que tipos de modelo y esfuerzo usar". Evidence-backed research on how to route by model type and effort, every claim with a fetched source URL and read date, tagged per the kit (Measured, Inferred, Assumed, Unknown).
- **S3 Model map.** "de momento solo quiero mapear los mas reciente de claude, gemini inglcyendo el 4, GPT y open soruces ones que peudan estar en local". The latest Claude, Gemini (including Gemini 4 if it exists; if it does not, say so with the source), GPT, and open-source models runnable locally: ids, context, price, effort/thinking controls, strengths, and how each harness (Claude Code, pi, Gemini CLI, Codex CLI, local runtimes) selects model and effort.
- **S4 Multi-agent method.** "la metodologia de trabajo a la hora de lanzar multiagentes, deberian poder seleccionar cual, que esfuerzo y cuando". A written method that, for each kind of task and role, selects which model, which effort, and when to launch (or not launch) a subagent.
- **S5 Deterministic evaluator.** "mas un script capaz de avaluar eso, de forma determinista esta beuno evaluar y saber que multiagentes lanzar de forma correcta pero que me de el mejor resultado posible." A script that, from a task descriptor, deterministically returns the multi-agent roster (role, model, effort, when) aiming at the best result, and evaluates routing decisions (same input, same output; tests with negative controls).
- **S6 Language and evidence.** Artifacts in English; chat in Spanish. No model, price or capability enters the catalog without a fetched source; prices expire, so every entry carries its read date.

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| R1 | S2, S3 | worker | done | `odd/research/model-router/anthropic.md` (146 lines, 89/89 quotes checked) |
| R2 | S2, S3 | worker | done | `google.md` (198 lines, 66/66 quotes; Gemini 4 = `gemini-4-argon` GA 2026-10-13, only member) |
| R3 | S2, S3 | worker (crashed before report) | done | `openai.md` (127 lines); R6 spot-check 6/6 quotes; pricing page 403 |
| R4 | S2, S3 | worker (crashed before report) | done | `local.md` (162 lines); R6 spot-check 6/6 quotes, one claim (`gpt-oss:20b` in Codex docs) failed and is not used |
| R5 | S2, S4 | worker (retry) | done | `methods.md` (219 lines, 63/63 quotes) |
| R6 | S2, S4 | worker (context backstop) | done | `routing-method.md` (220 lines): catalog per tier, decision table P1-P6/B0-B7, escalation ladder, routing log, harness mapping, 10 open decisions |
| R7 | S3, S6 | worker | todo | model catalog config with effort levels and read dates |
| R8 | S5 | worker, test-first | todo | deterministic router + evaluator script |
| R9 | S1, S4 | worker | todo | wire the router into the kit (roles, skills, init, log) |
| R10 | S1-S6 | independent verifier | todo | verdict per S# |

## Log

- **L1** (user, 2026-10-16, verbatim): "necesito que se trabaje en el routing\n\nhaz un /deepresearch donde se haga la investigacion referente a como hacer un router referente a que tipos de modelo y esfuerzo usar, de momento solo quiero mapear los mas reciente de claude, gemini inglcyendo el 4, GPT y open soruces ones que peudan estar en local, la metodologia de trabajo a la hora de lanzar multiagentes, deberian poder seleccionar cual, que esfuerzo y cuando, mas un script capaz de avaluar eso, de forma determinista esta beuno evaluar y saber que multiagentes lanzar de forma correcta pero que me de el mejor resultado posible."
- **L2** (decision, coordinator): there is no `/deepresearch` skill in this harness; the deep research runs as five parallel read-and-fetch lanes (R1-R5) that each fetch official pages and write one dossier with verbatim quotes, URLs and read dates. Code waits until the English port (`port/update`) lands, to avoid editing files the port is renaming.
- **L3** (evidence, R1-R6): five dossiers + routing method written in `odd/research/model-router/`; all fetch temp dirs deleted. Key findings: learned routers degrade on unseen task types, so a deterministic rule table fits until Phase 2 data exists; cascades need an external verifier; voting is non-monotone; more effort beats a bigger model on easy/intermediate tasks but not the hardest. Ten owner decisions open in `routing-method.md` §7.
- **L4** (user, 2026-10-16, answers): defaults "Sí, tomá tus recomendaciones" (optional `Budget (USD)` in the card; offline from `project.json` `offline: true` or `METODO_OFFLINE=1`; max 3 parallel subagents, depth 1; trial slot off by default; Gemini 4 Argon replaces 3.1 Pro preview as Google large candidate; log at `runs/routing.jsonl`); authority "El router (recomendado)" (router decides model and effort at launch, frontmatter only as fallback); models "Prueba de admisión primero (recomendado)" (Haiku/Sonnet/Opus 5.5 enter as candidates, Fable 5.1 stays orchestrator until Opus 5.5 is measured); local "Solo nivel chico y solo offline/privado (recomendado)".
- **L5** (user, 2026-10-16, verbatim): "¿Actualizo los modelos actuales a la familia 5.5? aqui es un rotundo SI, son mejores a nivel de costo". Overrides the L4 answer: Haiku 5.5, Sonnet 5.5 and Opus 5.5 become the admitted Claude incumbents now and Opus 5.5 the orchestrator, by owner decision recorded as such (not measured by the multi-provider-routing §4 admission test); Fable 5.1 stays available as an explicit escalation. Applied to agent frontmatter (pinned full ids, so a subagent never inherits the main session model through a family alias), `model-tiers.json` and `multi-provider-routing.md` in the port tree before publishing.
- **L6** (user, 2026-10-16, verbatim): "fable 5.1 peude estar para cosas puntiales, y para verificacion de procesos que ameritan un nivel mas alto de pensamiento, bajo aprobacion". Fable 5.1 is never in a default roster; the router may only PROPOSE it (rule id `escalate-fable`) for (a) one-off owner-named tasks and (b) verification of processes that warrant the highest reasoning (e.g. a P0 on a critical path, an unresolved adversary disagreement after the large judge, a high-tier receipt escalated twice). The roster entry carries `requires_approval: true`; nothing launches on Fable until the owner approves (`receipt_acknowledge`-style decision recorded in the routing log). Tests: no input produces Fable without the approval flag; an approved escalation launches it; a denied one falls back to Opus 5.5 at xhigh.
