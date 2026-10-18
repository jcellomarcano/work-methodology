# Feature: agent-permissions (research only)

**Objective.** Research how each agent could carry a permission checker, like user roles with permissions: least privilege to the given scope and working folder, and when outside it, ask for a temporary or per-session grant, without breaking auto mode and bypass, which stay useful.
**Status.** Research only (owner: "vale la pena investigar, mas no hacer ahora"). No code until the owner decides.

## Specs

- **S1 Scoped permissions per agent.** "los agentes tambein deberian tener dentro un verificador de permiso como cuando manejamos unos roles de usuario con permisos a ciertas cosas, minimo al scope dado y a la carpeta donde se trabaja y si no, preguntar por permisos, temporarles o por esa sesion". Each agent works with least privilege bound to its scope and folder; outside it, an explicit grant (one-time, temporary, or for the session).
- **S2 Keep auto mode and bypass.** "porque el automode y bypass son cosas que tambien son utiles". The design must coexist with each harness's auto/bypass modes, stating what still holds there.

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| A1 | S1, S2 | worker (research) | done | `odd/research/permissions/agent-permissions.md` |

## Log

- **L1** (user, 2026-10-18, verbatim): "los agentes tambein deberian tener dentro un verificador de permiso como cuando manejamos unos roles de usuario con permisos a ciertas cosas, minimo al scope dado y a la carpeta donde se trabaja y si no, preguntar por permisos, temporarles o por esa sesion, pero esto es algo que resolveremos mas adelante, vale la pena investigar, mas no hacer ahora porque el automode y bypass son cosas que tambien son utiles"
- **L2** (evidence, A1): dossier written (47/47 quotes). Today only shared build files, `.claude/**` for subagents, subagent delivery, force push and the call budget are blocked; scope is warn-only, reads, Bash writes and network are unchecked, hooks fail open. Native deny rules survive bypass in Claude Code and OpenCode `--auto`; Codex hook `ask` fails open. Eight owner questions in §5, parked until the owner resumes this feature.
