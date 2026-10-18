# Feature: harness-guides

**Objective.** Clear, verified instructions for using the kit with Codex CLI, Google Antigravity, OpenCode and local models (Ollama, LM Studio, llama.cpp), next to the existing Claude Code and pi support, with an honest support matrix in the README.
**Branch.** `feat/harness-guides` from published main b659bd7. No new installers in this feature (owner decision L2).

## Specs

- **S1 Other harnesses.** "la idea es que esto tambien pueda conectarse con codexantygravity, opencode, y si hay modelos locales, que decierta forma de una isntrucciones para eso." Instructions per harness: how its agents/subagents, MCP servers, hooks or guards, instruction files (AGENTS.md / GEMINI.md), and model + effort selection map onto the kit's roles, skills, `metodo` MCP server and router.
- **S2 Scope.** Owner chose "Investigar + instrucciones en el README": research from official docs, step-by-step guides and a support matrix stating what works, what partly works and what does not; no installers.
- **S3 Evidence.** Every harness claim cites an official page with read date, or a local `--help` run marked Measured; unverified steps are marked as such.

## Tasks

| ID | Specs | Route | Status | Evidence |
|---|---|---|---|---|
| H1 | S1, S3 | worker (research: Codex CLI) | todo | `odd/research/harnesses/codex.md` |
| H2 | S1, S3 | worker (research: Antigravity) | todo | `odd/research/harnesses/antigravity.md` |
| H3 | S1, S3 | worker (research: OpenCode) | todo | `odd/research/harnesses/opencode.md` |
| H4 | S1, S2 | worker | todo | `docs/08-harnesses.md` guide + README matrix + local-model section |

## Log

- **L1** (user, 2026-10-18, verbatim): "la idea es que esto tambien pueda conectarse con codexantygravity, opencode, y si hay modelos locales, que decierta forma de una isntrucciones para eso. ESto qesta en el Readme?" Answer: not in the README; only Claude Code and pi have installers; Codex and local models exist only as router research; OpenCode and Antigravity were not researched.
- **L2** (user, 2026-10-18, answer): "Investigar + instrucciones en el README".
