# Research C2: Engram as an optional, queryable memory (read 2026-10-18)

Scope: spec S1 and S3 of `odd/tasks/context-optimization.md`. Sources fetched with `curl -sL` into `$TMPDIR/c2engram`
on 2026-10-18 (§8). Every verbatim quote carries a source id and was matched by script (§8). Kit citations are
`file:line@44bd74c`. Tags: Measured (run here, or kit data), Reported, Inferred, Assumed, Unknown. Privacy: this
file holds aggregate counts and byte sizes only; no memory title or content was copied.

## 1. What Engram is and how it is queried

Engram is one Go binary over SQLite + FTS5 (`~/.engram/engram.db`), reached via CLI, MCP stdio, HTTP and a TUI [E2].
Installed: `engram 3.4.0`, the latest release (2026-10-12) [E11] [Measured]. `main` docs already list 26 MCP tools [E4];
the v3.4.0 tag and the local `--help` say 23 [E3] [L1], so this dossier reads the docs at the tag.

| Surface | Exact names and parameters (v3.4.0) | Source |
|---|---|---|
| CLI read | `search <query> [--type] [--project P\|--all] [--scope] [--limit N] [--match all\|any]`; `context [project] [--project P\|--all] [--scope]`; `timeline <obs_id> [--before N] [--after N]`; `stats [--project P\|--all]`; `doctor [--json] [--project P] [--check CODE]` ("read-only operational diagnostics") | [L1] |
| CLI write (not run) | `save <title> <msg> [--type] [--project] [--scope] [--topic TOPIC_KEY]`, `delete`, `import`, `sync`, `projects merge/prune`, `setup`, `cloud` | [L1] [E10] |
| MCP profiles | `engram mcp --tools=agent` (19 tools), `admin` (4: `mem_delete`, `mem_stats`, `mem_timeline`, `mem_merge_projects`), `all` (23, the default) | [L1] [E8] |
| MCP read tools | `mem_current_project`, `mem_context(project, scope, max_bytes, compact)`, `mem_search(query, type, project, all_projects, scope, match_mode, response_format, limit)`, `mem_get_observation(id, project)`, `mem_list_projects`, `mem_review(action=list)`, `mem_doctor` | [E3] [E8] |
| MCP write tools | `mem_save(title, type, scope, topic_key, content, capture_prompt)`, `mem_update(id, expected_project, …)`, `mem_suggest_topic_key`, `mem_session_summary`, `mem_session_start/end`, `mem_save_prompt`, `mem_capture_passive`, `mem_judge`, `mem_compare`, `mem_pin/unpin` | [E3] [E8] |

- **Search.** FTS5 over title, content, type and project. `match_mode` is "all" (default, AND) or "any" (OR) [E8].
  `limit` is "Max results (default: 10, max: 20)" [E8]. Each hit is a preview: the store cuts content at 300
  characters (`substr(content, 1, 300)`) [E9]. The README says "Search results are previews, not the complete
  record." [E2], so full content needs `mem_get_observation`.
- **Context.** "MCP `mem_context` uses a 16 KiB default budget for the complete tool result and caps `max_bytes` at
  64 KiB." [E3] `compact=true` drops the content previews and keeps type and title [E3]. The CLI `context` has no byte
  cap in 3.4.0 [E10], and it rejects `--help` ("unknown context flag: --help") [L1].
- **Topic keys.** "When `topic_key` is provided, `mem_save` upserts the latest observation in the same `project + scope
  + topic_key`, incrementing `revision_count` and attributing it to the latest writer session." [E3]
- **Scopes.** `project` (default), `personal`, `global`; `scope: personal` with no project searches across all
  projects [E3]. "Scope is a **search and filter signal**, not a privacy boundary." [E6]
- **Conflicts.** `mem_judge` records `related | compatible | scoped | conflicts_with | supersedes | not_conflict`;
  search shows `supersedes:` / `superseded_by:` / `conflicts:` lines [E3]. Staleness: results carry `state` `active` or `needs_review` (`review_after` from a per-type decay policy) [E3].
- **Plugin (Claude Code).** On session start it creates a session and "Injects previous session context into
  Claude's initial context" [E5]; on compaction it re-injects context; on prompt submit it loads tools and can add
  a save reminder [E5]. The intended mental model is invisible infrastructure: "If you're thinking about engram while
  working, something went wrong." [E7]

Positioning [Reported, Inferred]. The Anthropic memory tool is client-side files, and "Memory supports just-in-time
context retrieval." [E12] Anthropic calls structured note-taking "persistent memory with minimal overhead" [E13].
MemGPT pages between memory tiers ("we propose virtual context management") [E14]. Letta injects "core" memories into
context and keeps all other state in a database [E17]. Generative Agents "synthesize those memories over time into
higher-level reflections, and retrieve them dynamically to plan behavior" [E15]. Mem0 extracts and consolidates
memories and reports that it "saves more than 90% token cost" against full context on LOCOMO [E16]. Engram is the
plain end of this range. It is lexical FTS5 with no embedding ranking or importance score. The agent writes what
gets stored. There is no self-editing in-context block, only pinned observations and session summaries. Mem0's
90% comes from long chat dialogues and should not be carried over to coding sessions [Inferred].

## 2. Cost model

Bytes measured on this machine for the kit's own project, with contents piped to `wc -c` and discarded [Measured]:

| Call | Bytes returned | Notes |
|---|---|---|
| `engram context --project <kit>` (CLI, no cap) | 10,150 | MCP default would cap at 16,384 [E3] |
| `engram search <q> --project <kit>`, 5 queries × 2 modes | 46 – 4,758 (0 – 10 hits) | default limit 10, previews ≤ 300 chars; `--match any` doubled hits on one query (5 → 10) and turned 0 → 4 on another |
| Memory Protocol text (DOCS v3.4.0 §Memory Protocol) | 4,026 | sits in the system prompt on every turn when the plugin injects it [E5] |
| Re-reading instead: `CONTEXT-PACK.md` / task doc / `phase1-findings.md` / `methodology.md` | 6,984 / 4,321 / 15,137 / 15,814 | the kit's own sources of truth |

At about 4 bytes per token [Assumed], a search costs 0.01k–1.2k tokens, a default `mem_context` up to ~4k tokens, and the
protocol ~1k tokens on every turn. Break-even [Inferred]: a recall returning `r` bytes that replaces a read of `a`
bytes with probability `h` pays when `h·a > r`. A 4.7 KB search that replaces a 15 KB doc needs `h ≥ 0.31`. If it
only replaces the 4.3 KB task doc, it never pays: the task doc is smaller and authoritative. Engram pays most when
the alternative is *re-deriving* a decision that was reached in conversation and written nowhere. That costs several
turns of reasoning and tool calls, an order of magnitude above a 1–2 KB targeted search [Inferred, not measured].
On 1M-token windows, the main recall trigger (recovery after compaction) is rare: median 0 compactions per session
(`08-benchmark/reports/phase1-findings.md:49@44bd74c`) [Measured].

## 3. Why the kit's measured recall is 0 and 92% of sessions saved nothing

Data: 405 Engram sessions, 373 with zero observations; recall calls median 0 in every group; 21 project-a sessions
recalled at least once (`phase1-findings.md:77-78@44bd74c`) [Measured]. Causes with evidence:

1. **The kit wires writes only.** `engram_bridge.py` has `save` and no read path (`03-tools/lib/engram_bridge.py:62-77`).
   The two recall calls are left manual (`00-principles/runtime-adapters.md:112-115`). No role, skill, `CONTEXT-PACK.md`
   or hook names `mem_context`/`mem_search` (grep over `01-roles 02-skills CONTEXT-PACK.md AGENTS.md 03-tools/hooks`)
   [Measured]. An unprompted behaviour shows up at median 0 [Inferred].
2. **Subagents cannot recall.** Every role's `tools:` allowlist lists `mcp__metodo__*` and no `mcp__engram__*`
   (`01-roles/agents/generic-*.md:4`) [Measured]. Most kit work runs in subagents (subagent token share 0.45 in kit
   multi-agent cells, `phase1-findings.md:44`) [Measured].
3. **Bridge saves land outside the session.** The bridge shells `engram save` (`engram_bridge.py:70-72`). For that
   path the docs say "The CLI fallback writes to an independent project manual-save session and does not bind it to
   the current MCP session." [E3] So a session whose receipts and handoffs *were* saved still counts as a session with zero
   observations [Inferred; the share of the 373 that this explains is Unknown].
4. **The denominator counts every runtime session.** The plugin "Creates a new session via the API" on every start [E5],
   short ones too, and Engram is not "a transcript sink" [E2]: zero saves is expected with no durable decision [Inferred].
5. **Passive recall is invisible to the metric.** `transcript_metrics.py:45` counts recall as tool calls only. The
   plugin's session-start injection [E5] is not a tool call, so the recall median of 0 undercounts context that *was*
   injected. Whether it was injected in these sessions is Unknown.
6. **The kit's saves duplicate files.** Receipt and handoff notes restate `out/` files (`rdd_receipt.py:506-515`,
   `handoff.py:62-69`). Feature state lives in `odd/tasks/` (`phase1-findings.md:82`). There was little to recall
   that a file did not already hold [Inferred].
7. **Store hygiene here.** `engram doctor --json` on 2026-10-18: 10 checks, 7 ok, 2 warnings, 1 error. The warnings
   are `ambiguous_active_runtime_sessions` (2 findings; omitted-session writes "fail closed") and
   `session_project_directory_mismatch` (1). The error is `sync_target_closed_space` (4) [L1] [Measured]. Doctor's own
   reason: "Project/directory drift can cause agents to retrieve or save memories under the wrong project scope." [L1]

## 4. Usage patterns that save context

- **Session start, resume only.** Read the task doc first. Then call `mem_context(compact=true, max_bytes=4096)`
  once; compact keeps type and title only [E3]. That is a ≤1k-token index instead of the 16 KiB default [Inferred].
- **Targeted search before exploring.** Run `mem_search(query=<feature or bug noun>, limit=5)` with the default
  `match_mode=all`. Retry once with `any` only on zero hits. Open a hit with `mem_get_observation` only when its
  preview is relevant: "Retrieve progressively" [E2]. Never use `all_projects=true` unless the owner asks.
- **Decision records with a stable key.** Use `mem_save(type=decision, topic_key=<feature>/<decision>)`, with
  What/Why/Where/Learned in ≤ 600 bytes, and cite the file that holds the evidence. The upsert keeps the latest state
  only [E3], so history stays in git and `out/` (`runtime-adapters.md:107-110`).
- **Handoff notes.** One `mem_session_summary` when a feature spans sessions, pointing at `odd/tasks/<feature>.md`.
- **Do NOT store**: anything already in a tracked file (task docs, receipts, code), raw tool output or transcripts
  [E2], secrets or client data (`<private>` tags redact, but scope is not a privacy boundary [E6]), personal files
  (`AGENTS.md` rules), absolute home paths, and speculation that has not been verified.

## 5. Deterministic ON/OFF rule [Inferred]

Inputs, all computable without an LLM:
- `E`: `METODO_MEMORY` is not `off` and `memory.enabled` is true (`03-tools/config/project.json:76`). `B`: `engram version` exits 0.
- `P`: `mem_current_project` returns a non-empty `project` with empty `available_projects`, and `doctor --check
  session_project_directory_mismatch --project <p>` is ok.
- `S`: the task or repo is marked sensitive (client data, secrets, `*.personal.*`). `R`: the caller is parent or subagent.
- `K`: task kind, one of trivial (one file, mechanical or docs), standard, or multi-session (an `odd/tasks/` doc with ≥ 2
  open tasks).
- `M`: a resume, meaning the task doc has a Log entry from an earlier day, or the session follows a compaction.

First matching row wins:

| # | Condition | Reads | Writes |
|---|---|---|---|
| 1 | not `E` or not `B` | off | off (bridge returns False already) |
| 2 | `R` = subagent | off; the parent forwards what is relevant | off |
| 3 | `S` | explicit `project` only, never `all_projects` | off (no `mem_save`, bridge off for that repo) |
| 4 | not `P` | explicit `project` only | off until the project resolves |
| 5 | just compacted | `mem_context(compact, 4096)` once | the compacted summary via `mem_session_summary` [E5] |
| 6 | `M` | task doc, then `mem_context(compact, 4096)` + ≤ 2 `mem_search(limit 5)` | decisions (topic_key) + handoff at close |
| 7 | `K` = multi-session | 1 `mem_search(limit 5)` on the feature name before exploring | decisions + handoff |
| 8 | `K` = trivial | off | only a non-obvious bugfix or decision |
| 9 | otherwise | 1 `mem_search(limit 5)` only if the prompt names prior work | decisions only |

Session length enters only through `M` and row 5 (its effect is unknown until H5 is tested).
Kill switch [Assumed thresholds]: after 20 sessions under rows 5–7, if `recall_used_rate < 0.2` and resume cost
(M53) is not lower than in `kit-no-engram`, the default flips to `memory.enabled: false`.

## 6. Metrics, all deterministic

| Metric | Formula | Computable from |
|---|---|---|
| recall calls / session | count of `ENGRAM_RECALL` tool calls | `transcript_metrics.py:45` (exists) |
| bytes injected | Σ bytes of engram tool results + session-start hook output | transcripts (new parser field) |
| recall used rate | recalls whose returned `#id`, topic key or title reappears later in the session (a `mem_get_observation` or a citation) ÷ recalls | transcripts |
| empty-search rate | results starting "No memories found" [E10] ÷ searches | transcripts |
| saves / session | observations per session, runtime and manual-save sessions counted apart | `engram_metrics.py` export plus session kind |
| upsert ratio | `upserted ÷ with_topic_key` | `engram_metrics.py:74-75` (exists) |
| stale count | results with `state: needs_review`; `mem_review list` size | transcripts, export `review_after` |
| conflict debt | `relations_pending`, `relations_by_relation` | `engram_metrics.py:91-92` (exists) |
| duplicate saves | saves whose body names an `out/` or `odd/` path | export, regex on body (stays local) |
| resume cost | tokens until first edit in resumed sessions, ON vs OFF | Phase 2 arm `kit-no-engram`, M53 (`phase1-findings.md:84`) |

## 7. Risks and mitigations

| Risk | Evidence | Mitigation |
|---|---|---|
| Stale memory read as fact | an upsert keeps only the latest state [E3]; `needs_review` exists [E3] | cite the file behind every saved decision; treat a recall as a pointer, then verify in the file (evidence-or-silence) |
| Privacy | scope "not a privacy boundary" [E6]; the plugin stores prompts (1,585 prompt rows across 7 projects here [L1]); the bridge body holds absolute paths (`rdd_receipt.py:511-513`) | rule row 3; never save client data or personal files; keep `engram sync`/cloud off unless the owner opts in |
| Cross-project leakage | `all_projects=true` and `scope: personal` cross projects [E3]; drift warning live here [L1] | explicit `project` in reads; forbid `all_projects` by default; rule row 4 |
| Conflicts | phase 1: related 204, not_conflict 163, supersedes 18 (`phase1-findings.md:80`) | one topic_key per decision; judge only on `judgment_required`; report `relations_pending` |
| Fixed context cost with no recall | ~4 KB protocol per turn [Measured bytes]; 19 tool schemas (bytes Unknown) | load the tools deferred; drop the protocol where rule rows 1–4 say off |
| Version drift | `main` docs 26 tools vs the installed 23 [E4] [L1] | pin docs to the installed tag; `engram version` in `doctor.sh` |
| CLI help can run commands | `engram search --help` ran a search for the literal string `--help` [L1] | use `engram help` only; never `--help` on `setup`, `sync`, `mcp` |

Uncertainties [Unknown]: whether session-start injection fired in the measured sessions; how many of the 373 empty
sessions had bridge saves in manual-save sessions; whether the bridge's type `context` (`engram_bridge.py:27`), outside
the documented type list [E3], filters well; the token cost of the MCP tool schemas.

## 8. Sources (read 2026-10-18; HTTP status of the fetch)

| Id | URL | HTTP |
|---|---|---|
| E1 | https://github.com/Gentleman-Programming/engram | 200 |
| E2 | https://raw.githubusercontent.com/Gentleman-Programming/engram/main/README.md | 200 |
| E3 | https://raw.githubusercontent.com/Gentleman-Programming/engram/v3.4.0/DOCS.md | 200 |
| E4 | https://raw.githubusercontent.com/Gentleman-Programming/engram/main/DOCS.md | 200 |
| E5 | https://raw.githubusercontent.com/Gentleman-Programming/engram/v3.4.0/docs/PLUGINS.md | 200 |
| E6 | https://raw.githubusercontent.com/Gentleman-Programming/engram/v3.4.0/docs/TEAM-USAGE.md | 200 |
| E7 | https://raw.githubusercontent.com/Gentleman-Programming/engram/main/docs/intended-usage.md | 200 |
| E8 | https://raw.githubusercontent.com/Gentleman-Programming/engram/v3.4.0/internal/mcp/mcp.go | 200 |
| E9 | https://raw.githubusercontent.com/Gentleman-Programming/engram/v3.4.0/internal/store/store.go | 200 |
| E10 | https://raw.githubusercontent.com/Gentleman-Programming/engram/v3.4.0/cmd/engram/main.go | 200 |
| E11 | https://api.github.com/repos/Gentleman-Programming/engram/releases/latest | 200 |
| E12 | https://docs.claude.com/en/docs/agents-and-tools/tool-use/memory-tool (→ platform.claude.com) | 200 |
| E13 | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | 200 |
| E14 | https://arxiv.org/abs/2310.08560 (MemGPT) | 200 |
| E15 | https://arxiv.org/abs/2304.03442 (Generative Agents) | 200 |
| E16 | https://arxiv.org/abs/2504.19413 (Mem0) | 200 |
| E17 | https://docs.letta.com/guides/agents/memory (→ /v1-sdk/concepts/stateful-agents) | 200 |
| L1 | local, read-only: `engram version`, `engram --help`, `engram search --help`, `engram context --help`, `engram stats --all`, `engram stats --project <kit>`, `engram doctor --json`, byte counts of `context`/`search` | n/a |

Quote check: `$TMPDIR/c2engram/quote_check.py` pulls every `"…" [Ex]` pair from this file and asserts it is a
whitespace-normalized substring of the fetched source text: 22 quotes, 0 failed. Not run: `mcp --help` and `setup --help`
(could start a server or write config), `stats --help` and `doctor --help` (top-level help documents them; subcommands
do not parse `--help`), `conflicts stats` (help does not say read-only), and `export`.
