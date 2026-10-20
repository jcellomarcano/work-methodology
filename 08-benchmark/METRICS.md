# Metric catalogue

Every number the benchmark reports comes from one row of this catalogue. A number without a row is not reported.

Spec: `odd/tasks/methodology-benchmark.md` (S2–S18 map to the rows below).

## Labels

Each value carries one epistemic label, the kit's own vocabulary (`00-principles/methodology.md`, COM-09):

| Label | Meaning |
|---|---|
| Measured | Read directly from a record (token counts, timestamps, exit codes). |
| Tested | Produced by running something (tests, lints, seeded-defect checks). |
| Inferred | Derived from measured values through a stated rule (for example "kit session" = session that calls a `mcp__metodo__*` tool). |
| Assumed | Not derived from evidence; stated so it can be challenged. |
| Unknown | No source exists. Reported as Unknown, never estimated. |

Each measurement attempt also carries one status: `ok`, `failed` (the script ran and could not produce the value; the error is kept), `not-run`. "Failed" is a status, not a label, so the kit's COM-09 vocabulary stays intact.

## Arms and boundaries

- **Phase 1 (retrospective).** Unit = one Claude Code session transcript. `before` = sessions in a project with no kit markers and dated before that project's adoption date; `after` = sessions on or after it. Adoption date per project = timestamp of the first session that calls a `mcp__metodo__*` tool, a `generic-*` subagent, or a kit skill (Inferred). The installer-file mtimes (project-b 2026-09-05, project-c 2026-09-05, project-a 2026-09-23, project-d 2026-09-30) are reported next to it as a cross-check.
- **Phase 2 (controlled).** Unit = one task run. Arms: `vanilla` (stock Claude Code), `kit` (full install), `kit-no-engram` (kit with Engram disabled). Same model, same effort, same tasks, N repetitions per cell, seeded defects known in advance.

Known Phase 1 confounders, stated once and attached to every before/after delta: task mix differs; model versions and Claude Code versions drift over July–October 2026; the user learns over time; sessions are not independent. Phase 1 therefore produces hypotheses, not causal claims.

## Rows

Sources: `T` = transcripts under `~/.claude/projects`, `G` = git history of the target repos, `E` = Engram (`engram export`), `L` = kit hook ledgers and receipts, `K` = kit source code, `P2` = Phase 2 run logs.

### Context and tokens (S6, S13)

| ID | Metric | Source | Method | Phase 1 | Phase 2 |
|---|---|---|---|---|---|
| M01 | Input tokens per session (sum of `usage.input_tokens` + cache reads + cache writes over assistant records) | T | `transcript_metrics.py` | Measured | Measured |
| M02 | Output tokens per session | T | same | Measured | Measured |
| M03 | Cache hit ratio = cache_read / (input + cache_read + cache_write) | T | same | Measured | Measured |
| M04 | Peak context occupancy = max over turns of (input + cache_read + cache_write) of one request | T | same | Measured | Measured |
| M05 | Compaction events per session | T | count of compaction/summary records | Measured | Measured |
| M06 | Tokens per completed task | T + G | session tokens ÷ commits or PRs produced in the session | Inferred | Measured |
| M07 | Share of tokens spent by subagents vs main thread | T | sidechain/agent records vs main | Measured | Measured |
| M08 | Share of tokens by model tier (haiku/sonnet/opus/fable) | T | `message.model` per request | Measured | Measured |
| M09 | Parent peak context in sessions with ≥1 subagent vs sessions with none, kit vs no-kit (S22) | T | M04 split by `subagents.count` and `kit.uses_kit` | Measured | Measured |

### Verbosity and latency (S6)

| ID | Metric | Source | Method | Phase 1 | Phase 2 |
|---|---|---|---|---|---|
| M10 | Assistant reply length in characters, per final reply (text blocks of the last assistant record before a user record) | T | `transcript_metrics.py` | Measured | Measured |
| M11 | Reply length ÷ user prompt length | T | same | Measured | Measured |
| M12 | Time to first assistant record after a user record (seconds, from `timestamp`) | T | same | Measured | Measured |
| M13 | Turn wall-clock = time between a user record and the next user record | T | same | Measured | Measured |
| M14 | Tool calls per turn | T | count of `tool_use` blocks | Measured | Measured |

### Code quality and standards alignment (S6, S11)

| ID | Metric | Source | Method | Phase 1 | Phase 2 |
|---|---|---|---|---|---|
| M20 | Shape metrics delta per commit (bang-bang, lateinit, println, long functions) | G + K | `shape_metrics.py` / `baseline.delta` before and after each commit | Tested | Tested |
| M21 | Duplication (CPD) delta | G + K | `duplication_cpd.py` | Tested | Tested |
| M22 | Lint verdicts on replies and comments (`output_lint`, `comment_gate`) | T + K | run lints over `after` replies; `before` replies get the same lints as a counterfactual | Tested | Tested |
| M23 | Share of commits that touch tests together with code | G | `git_metrics.py` | Measured | Measured |
| M24 | Conventional Commit compliance rate | G | regex over subject lines | Measured | Measured |
| M25 | Seeded-defect recall: defects found ÷ defects seeded | P2 | only Phase 2 | Unknown | Tested |
| M26 | False findings: reported defects that do not exist | P2 | blind judge verification | Unknown | Tested |

### Judges, adversaries, RDD/ODD (S7)

| ID | Metric | Source | Method | Phase 1 | Phase 2 |
|---|---|---|---|---|---|
| M30 | Review rounds per feature and findings per round | T + L | count judge/adversary subagent runs and their findings records | Measured where ledgers exist, otherwise Inferred from transcripts | Measured |
| M31 | Findings confirmed by a second blind judge ÷ findings raised (agreement) | T | parse judgment-day outputs | Inferred | Measured |
| M32 | Blockers caught before merge vs after (bugfix commits following a PR) | G | commits tagged fix touching files of a PR within 14 days | Inferred | Measured |
| M33 | Cost of a review round (tokens) | T | M01+M02 scoped to review subagents | Measured | Measured |
| M34 | RDD receipts issued, voided, acknowledged | L | `out/rdd/*.receipt.json` | Measured (expected sparse) | Measured |

### Delivery and communication (S4, S8, S17)

| ID | Metric | Source | Method | Phase 1 | Phase 2 |
|---|---|---|---|---|---|
| M40 | Lead time per feature branch: first commit → merge | G | `git_metrics.py` | Measured | Measured |
| M41 | Commits per day and lines per commit | G | same | Measured | Measured |
| M42 | PR or commit body conformance to the kit template (`pr-message`) | G + K | template field presence | Tested | Tested |
| M43 | Share of replies carrying epistemic tags (COM-09) | T + K | `output_lint` over final replies | Tested | Tested |
| M44 | Failure reports (`--type fallo`) produced per failed check | T | count | Inferred | Measured |

### Memory: Engram (S3)

| ID | Metric | Source | Method | Phase 1 | Phase 2 |
|---|---|---|---|---|---|
| M50 | Observations saved per session, by type | E | `engram_metrics.py` | Measured | Measured |
| M51 | Recall calls per session (`mem_search`, `mem_context`, `mem_get_observation`) | T | tool_use names | Measured | Measured |
| M52 | Recall hit: a recalled observation's id or title appears in the reply or next edit | T + E | string match | Inferred | Inferred |
| M53 | Resume cost: tokens spent before the first edit in a session that continues a feature, with vs without Engram | T | first `Edit`/`Write` offset | Inferred | Measured (ablation arm) |
| M54 | Sessions with zero observations ÷ sessions | E | count | Measured (373/405 on 2026-10-13) | Measured |

### Multi-agent and router (S12, S14)

| ID | Metric | Source | Method | Phase 1 | Phase 2 |
|---|---|---|---|---|---|
| M60 | Subagent runs per session, by type (Explore, generic-judge, review-*) | T | Agent tool_use `subagent_type` | Measured | Measured |
| M61 | Delegation reason recorded (trigger named in the prompt) | T | regex over Agent prompts | Inferred | Measured |
| M62 | Model chosen per agent role vs the policy in `model-routing.md` | T + K | `message.model` of sidechain records vs frontmatter | Measured | Measured |
| M63 | Effort level per request | T | not present in transcripts | Unknown | Measured |
| M64 | Router decisions logged | L | none exist (`model-tiers.json` is read by no code) | Unknown | Measured |
| M65 | Context handed to each subagent: Agent prompt length and the subagent's own peak context (S22) | T | Agent `tool_use.input.prompt` length; subagent file M04 | Measured | Measured |
| M66 | Compactions per 1M input tokens, split by with/without subagents and kit vs no-kit; tokens dropped per compaction (S22) | T | `compact_boundary` pre/post | Measured | Measured |

### Context method and delegation (`odd/tasks/delegation-context.md` S3, S4)

All rows are `transcript_metrics.py` fields under `sessions[].context_metrics.<key>`; each value carries its `id` and `label`. Tokens marked "est" are `ceil(chars/4)` (the kit's proxy, Inferred); tokens from `usage` are Measured. No path, text, title or hash leaves the script: only counts, sizes and role names.

| ID | Metric | Source | Method (`<key>`) | Phase 1 | Phase 2 |
|---|---|---|---|---|---|
| M100 | Per-role peak context vs the role's contract cap | T + K | `per_role_peak`: per subagent run, M04 of its `agent-*.jsonl`; role = `agentType` of the `.meta.json`, else the `subagent_type` of the Agent call it answers; cap = `max_context_tokens` of `01-roles/agents/<role>.contract.json` (`--contracts`); per role `runs`, `peak_max`, `over_cap_runs` (peak > cap), `peak_to_cap_max`; no contract → cap null | Measured | Measured |
| M101 | Tool-output share of input | T | `tool_output_share`: Σ est tokens of main-session `tool_result` text (by tool) ÷ fresh input tokens Σ(`input_tokens` + `cache_creation_input_tokens`); meaningful with prompt caching on (the Claude Code default) | Inferred | Inferred |
| M102 | Re-read ratio | T | `reread`: main-session `Read` calls minus distinct `file_path` ÷ `Read` calls; also same path+offset+limit, and over main + every subagent (`all_contexts`) | Measured | Measured |
| M103 | Subagent report size vs the 2,000-token cap (D9) | T | `subagent_reports`: est tokens of the `tool_result` answering each `Agent`/`Task` call, in call order; `over_cap` = est > 2,000; per role | Inferred | Inferred |
| M104 | Startup load | T | `startup_load`: input + cache_write + cache_read of the first deduplicated request (`usage`), main session and per subagent role; null without usage | Measured | Measured |
| M105 | Engram recall-used rate | T | `recall_used`: recalls = `mem_search`/`mem_context` calls; keys from each result: `#<id>`, `"id": n`, `ID: n`, topic keys, titles (≥ 8 chars); used = a key appears in a later assistant text or tool input (`#<id>`, an engram call with that `id`, topic substring, title case-insensitive); `empty` = no key extracted; rate = used ÷ recalls | Inferred | Inferred |
| M106 | Delegation ratio vs the router (S3) | T + L | `delegation` (`--routing-log`): router decisions = routing-log lines with `status: ok` whose `inputs_hash` appears in a main-session tool result, each counted once; asked = their `launch: run` entries by `delegate`; launched = `Agent`/`Task` calls by `subagent_type`; delegated = Σ role min(launched, asked subagent); ratio = delegated ÷ asked subagent; `unrequested_launches` = Σ role max(0, launched − asked); no log → status `not-run` | Inferred | Measured |
| M107 | WARN act rate | T | `warn_act`: fires = distinct `METODO-WARN <kind>:` lines at line start in a `hook_*` attachment or a tool result (not Read/Grep/Glob output); trigger = the call the result or attachment `toolUseID` names, else the last earlier call; next = first call of a later assistant message; acted = next call's tool family differs (Edit/Write/MultiEdit/NotebookEdit are one family); rate = acted ÷ judged (fires with trigger and next) | Inferred | Inferred |

Limits: M101/M103 count main-session results only; a background `Agent` call's result is its launch notice, not the report; M106 matches decisions only when the route result (MCP `route` or `route.sh` output) is in the transcript; M107 sees only warns written into the transcript.

### Determinism, scripts, lints (S10, S11)

| ID | Metric | Source | Method | Phase 1 | Phase 2 |
|---|---|---|---|---|---|
| M70 | Byte-identical reruns of every benchmark script on the same input | K | unit test: run twice, compare bytes | Tested | Tested |
| M71 | Kit script coverage: scripts with tests ÷ scripts | K | count under `03-tools/lib` and `03-tools/tests` | Measured | Measured |
| M72 | Gate actions: deny/ask/warn per kind (`gate-push`, `no-verify`, `forbidden-path`) | L | ledgers | Measured (4 lines exist) | Measured |

### Skills, ways of working, MCP (S15, S16, S18)

| ID | Metric | Source | Method | Phase 1 | Phase 2 |
|---|---|---|---|---|---|
| M80 | Skills installed and skills invoked (per skill, per session) | T + K | `Skill` tool_use names vs `02-skills/*` | Measured | Measured |
| M81 | Cost of adding one skill: files touched, lines, registry update | G | commits that add a skill | Measured | n/a |
| M82 | MCP servers wired by the kit and calls to each per session | T + K | `.mcp.json` and `mcp__<server>__*` tool names | Measured | Measured |
| M83 | Mechanisms transferable without this tooling (ways of working) | K | reviewer judgment, listed with reasons | Assumed | Assumed |

### Influences (S5)

| ID | Metric | Source | Method | Phase 1 | Phase 2 |
|---|---|---|---|---|---|
| M90 | Each kit mechanism → stated influence → checkable citation | K | table in the report; citations verified with `cite_check.py` | Tested | n/a |

## Reporting rule

Every table in `reports/` lists, per cell: value, label, status, source script and its `tool_sha`. A cell whose status is `failed` or whose label is Unknown stays visible in the table; it is never dropped to make the table look complete.
