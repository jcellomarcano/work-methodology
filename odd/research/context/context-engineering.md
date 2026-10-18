# Research C1: context engineering for the main conversation and subagents (read 2026-10-18)

Scope: spec S1 and S2 of `odd/tasks/context-optimization.md`. Sources were fetched with `curl -sL` into
`$TMPDIR/c1ctx` on 2026-10-18 (list in §7). Every verbatim quote is followed by its source id and was matched
against the fetched text by script (§7). Tags: Reported (a source states it), Measured (kit data, cited
`file:line@87d504f`), Inferred (derived here by a stated rule), Assumed (a starting value to be tested).

## 1. What consumes context

| Consumer | Numbers | Tag |
|---|---|---|
| Startup load (system prompt, CLAUDE.md, auto memory, MCP tool names, skill listing) | Claude Code: "Before you type anything: CLAUDE.md, auto memory, MCP tool names, and skill descriptions all load into context" [S16]; its timeline uses illustrative counts (system prompt 4,200 tokens) [S16] | Reported |
| Instruction files | "target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence" [S12]; a CLAUDE.md up to 4 MiB still loads in full [S12]; Codex stops adding AGENTS.md files at `project_doc_max_bytes` (32 KiB default) [S24] | Reported |
| Tool and MCP schemas | "A typical multiserver setup (GitHub, Slack, Sentry, Grafana, and Splunk) can consume \~55k tokens in definitions before Claude does any work" [S9]; selection degrades "once you exceed 30–50 available tools" [S9]; Claude Code defers MCP definitions by default [S13] | Reported |
| Skill listing | budget "scales at 1% of the model's context window" [S15]; description + `when_to_use` truncated at 1,536 chars [S15] | Reported |
| File reads and tool outputs | MCP output warns above 10,000 tokens and is capped at 25,000 by default [S17]; results over 50,000 chars are saved to a file [S17]; Gemini CLI truncates tool output at 40,000 chars by default [S41] | Reported |
| History | every request re-sends "the system prompt, your project context, every prior message and tool result, and your new message" [S19]; "all previous input tokens for responses in the chain are billed as input tokens" (OpenAI) [S23] | Reported |
| Subagent reports | "Running many subagents that each return detailed results can consume significant context" [S11]; a subagent returns "a condensed, distilled summary of its work (often 1,000-2,000 tokens)" [S1] | Reported |
| Kit, parent peak context per session (median) | 353k before vs 257k with the kit (`08-benchmark/reports/phase1-findings.md:25`) | Measured |
| Kit, multi-agent cells | parent peak 373k (kit) vs 537k (no kit); subagent token share 0.45 vs 0.23; brief 2,873 vs 3,489 chars (`phase1-findings.md:44-45`) | Measured |
| Kit, cache and compaction | cache hit ratio 0.963 → 0.971 (`phase1-findings.md:26`); median 0 compactions per session, each dropping ~940k tokens (`phase1-findings.md:49`) | Measured |

Reading [Inferred]: the ~940k drop per compaction matches Claude Code's default auto-compact point on 1M-window
models, "about 967K tokens by default" [S18]. The kit's sessions therefore run with parent contexts in the
250k-540k band for most of their life and almost never compact: the harness lets the context grow far past the
lengths where §2 reports degradation. Cost is mostly cached re-reads (hit ratio 0.97), so the issue is quality and
latency more than price.

## 2. Evidence on degradation with long context [Reported]

- Anthropic: "as the number of tokens in the context window increases, the model’s ability to accurately recall
  information from that context decreases" and it "emerges across all models" [S1]. Claude docs: "As token count
  grows, accuracy and recall degrade, a phenomenon known as *context rot*" [S4]. Claude Code: "LLM performance
  degrades as context fills" [S14].
- Lost in the middle (TACL 2023): "performance is often highest when relevant information occurs at the beginning or
  end of the input context" [S28].
- RULER (COLM 2024, 17 models): "only half of them can maintain satisfactory performance at the length of 32K" [S30].
- NoLiMa (ICML 2025, 13 models, low lexical overlap): "At 32K, for instance, 11 models drop below 50% of their strong
  short-length baselines"; GPT-4o drops "from an almost-perfect baseline of 99.3% to 69.7%" [S29].
- Chroma, Context Rot (2025-07-14, 18 models): on LongMemEval, full prompts "average out to ~113k tokens", focused
  ones "~300 tokens", and "Across all models, we see significantly higher performance on focused prompts compared to
  full prompts" [S31].
- Length alone (EMNLP Findings 2025): with perfect retrieval, performance "still degrades substantially (13.9%--85%)
  as input length increases" [S32].
- Coding agent, white-box audit (2026-07, n=10 per arm): Codex "passes 8/10 runs in a 10,991-character clean context
  but only 3/10 in both a 299,140-character relevant context and an equal-length irrelevant context", trend-level
  (p = 0.0698); "A detailed external checklist passes 10/10 runs, compared with 5/10 for a generic self-check" [S34].
- Standing instructions over long horizons (HANDBOOK.md, 2026-07): "the strongest evaluated model passes 36.2% of
  trials"; agents "lose rule details over long horizons, and report compliance they did not achieve" [S37].
- Long-horizon search (2026-06): "the premature termination rate is positively correlated with context length" [S36].
- Google: single-needle retrieval reaches ~99%, but with multiple needles "the model does not perform with the same
  accuracy" [S26].
- Stale instruction files are a second kind of context rot: stale code references in "23.0% of repositories" [S38].

Limits [Inferred]: most results are synthetic retrieval on older models; none measures Opus 5.5 / Sonnet 5.5 on the
kit's tasks. The direction is consistent across 2023-2026 studies; the threshold is not (S34 found a second task with
no drop). Treat the direction (shorter is better) as established and any specific cutoff as Assumed until Phase 2 measures it.

## 3. Techniques for the main conversation (orchestrator)

| # | Technique | Source | Expected saving | Cost / risk |
|---|---|---|---|---|
| T1 | `/clear` between unrelated tasks; after two failed corrections start fresh with a better prompt | "If you've corrected Claude more than twice on the same issue in one session, the context is cluttered with failed approaches" [S14]; "`/clear` costs nothing" [S13] | resets context to the startup load | loses conversational state unless written down first (T7) |
| T2 | Compact at natural breaks, with a focus line, not mid-task | "run `/compact` at a natural break in your work, such as between tasks, instead of waiting for auto-compaction to trigger mid-task" [S19]; `/compact focus on the auth bug fix` [S16] | context drops to summary + startup + up to 5 recent files (files over 5,000 tokens come back as a path) [S16] | the summary request reads the whole history; uncached after a break [S19]; "overly aggressive compaction can result in the loss of subtle but critical context" [S1] |
| T3 | Lower the auto-compact window | `/autocompact 500k`, `autoCompactWindow`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, accepted 100K-1M [S18]; Codex `model_auto_compact_token_limit` [S25]; Gemini CLI `compressionThreshold` default 0.5 [S41]; pi `reserveTokens` 16384, `keepRecentTokens` 20k [S42]; OpenCode `compaction.auto` [S40] | caps peak context (M04) at the chosen value | more compactions, each a full-history request; summaries lose detail; no source gives the right value for Claude 5.5-class models |
| T4 | Re-inject what must survive compaction | path-scoped rules are "summarized away"; skill bodies re-injected "capped at 5,000 tokens per skill and 25,000 tokens total"; `SessionStart` hooks matching `compact` add their output [S16] | keeps the task document and gate state alive after compaction | put key rules at the top of each `SKILL.md`; truncation keeps the start [S16] |
| T5 | Tool-result clearing / observation masking | API `clear_tool_uses_20250919`: default trigger 100,000 input tokens, keep 3 tool uses [S6]; SWE-agent study: masking "halves cost relative to the raw agent while matching, and sometimes slightly exceeding, the solve rate of LLM summarization" [S33]; OpenCode `prune` [S40] | ~50% cost on SWE-bench Verified [S33] | breaks the cache prefix: use `clear_at_least` [S6]; Claude Code already clears old tool results itself ("expected rebuild") [S13], with no user knob found |
| T6 | Protect the prompt cache | order is `tools` → `system` → `messages`; tool-definition changes invalidate everything [S8]; a model switch makes the next request read history "with no cache hits" [S19]; Opus/Sonnet 5.5 cache hits at 0.05x base input [S8]; "Pick your model and effort level at the top of a session" [S19] | 95% off cached input on 5.5-class models [S8] | the kit already sits at 0.971 (Measured); gains are in not breaking it (no mid-session model/effort switch in the orchestrator, skill `model:` overrides count as switches [S19]) |
| T7 | Handoff and notes files instead of history | "Structured note-taking ... the agent regularly writes notes persisted to memory outside of the context window" [S1]; memory tool is client-side files under `/memories` [S7]; the research system saves its plan to Memory "since if the context window exceeds 200,000 tokens it will be truncated" [S2] | lets T1/T2 be cheap: state is on disk, not in the window | notes go stale (S38); the kit's task document and receipts already play this role |
| T8 | Deferred tools, CLI over MCP | tool search cuts the ~55k definition load "by over 85 percent, loading only the 3–5 tools Claude needs" [S9]; CLI tools "are still more context-efficient than MCP servers" [S13]; disable unused servers [S13] | up to tens of k startup tokens per server set | a deferred tool costs one search call; tool search off behind a custom `ANTHROPIC_BASE_URL` [S17] |
| T9 | Short instruction files, progressive disclosure | <200 lines CLAUDE.md [S12]; "Keep `SKILL.md` under 500 lines" [S15]; path-scoped rules load on demand [S12]; one level of progressive disclosure helps on large corpora, "A second, deeper routing level never helps" [S35] | startup tokens; adherence | detail moved out must still be findable (one level, named paths) |
| T10 | Filter tool output before it lands | "a hook can grep for `ERROR` and return only matching lines, reducing context from tens of thousands of tokens to hundreds" [S13]; `PostToolUse` `updatedToolOutput` replaces a result [S20] | 10-100× on logs and test runs [S13] | a filter can hide the line that mattered; keep the full output in a file and return its path |
| T11 | Just-in-time retrieval, not re-reading | keep "lightweight identifiers (file paths, stored queries, web links, etc.)" and load at runtime [S1]; query placed at the end of long context [S26] | avoids carrying whole files; avoids re-reads after compaction | exploration is slower than preloading [S1]; needs a map (the kit's cartographer) |

## 4. Techniques for subagents

| # | Technique | Source | Expected saving | Cost / risk |
|---|---|---|---|---|
| A1 | Isolate only verbose, self-contained work | use subagents when "The task produces verbose output you don't need in your main context" or "The work is self-contained and can return a summary"; stay in main when "Multiple phases share significant context" [S11] | parent keeps only the summary | Cognition: "Share context, and share full agent traces, not just individual messages" [S3]; a fresh subagent "may need time to gather context" [S11] |
| A2 | Short, complete brief with paths | a subagent "doesn't see your conversation history, the skills you've already invoked, or the files Claude has already read" [S11]; "Without detailed task descriptions, agents duplicate work, leave gaps, or fail to find necessary information" [S2]; teammates: "everything in the spawn prompt adds to their context from the start" [S13] | kit brief 2,873 vs 3,489 chars (Measured, `phase1-findings.md:44-45`) | too short → duplicated reads; pass the paths and line ranges the parent already read (kit rule: paths, never content, `agent-protocol.md` §1) |
| A3 | Bounded report, artifact handoff | "often 1,000-2,000 tokens" per report [S1]; "Subagents call tools to store their work in external systems, then pass lightweight references back to the coordinator" [S2] | report size is what the parent pays per subagent | a cap without a file for overflow drops findings; truncation must be flagged (`truncated: true`, `agent-protocol.md` §2) |
| A4 | Strip inherited startup load | a non-fork subagent loads "every level of the CLAUDE.md hierarchy" unless `omitClaudeMd: true` [S11]; "most rules don't need to reach the subagent itself" [S11] | the size of CLAUDE.md + rules per subagent run | a rule the role needs must be restated in its contract or brief |
| A5 | Minimal tools and MCP per role | frontmatter `tools`, `mcpServers` per subagent [S11]; bloated tool sets cause "ambiguous decision points about which tool to use" [S1] | schema tokens; fewer wrong calls | the kit already enforces `tools` by frontmatter (`agent-protocol.md` §6) |
| A6 | Turn and window caps per role | `maxTurns` returns output "marked as partial" [S11]; per-subagent `autoCompactWindow` 100,000-1,000,000 [S11] | bounds a runaway subagent | the kit enforces `max_tool_calls` only (`03-tools/hooks/budget.py:25`); `max_context_tokens` is declared in contracts but no hook reads it (Inferred from a grep of `03-tools`) |
| A7 | Scaling rules, not judgment | "Simple fact-finding requires just 1 agent with 3-10 tool calls" [S2]; "Early agents made errors like spawning 50 subagents for simple queries" [S2] | avoids needless fan-out; "multi-agent systems use about 15× more tokens than chats" [S2] | deterministic router already does this (`model-routing.md` Router) |
| A8 | Fork vs fresh | a fork "inherits the parent's system prompt, tools, and conversation history exactly, so its first request reads the parent's cache" [S19]; fresh subagents get a 5-minute TTL by default [S19] | forks: cheap cache; fresh: small window | forks drop input isolation [S11]; reviewers need a fresh context to stay independent [S14] |
| A9 | Verify against an external checklist | checklist 10/10 vs generic self-check 5/10 [S34]; "have a subagent review the diff in a fresh context and report gaps" [S14] | fewer lost requirements late in long runs | costs one more run; the checklist must be deterministic (C4 done gate) |

## 5. What the kit can measure deterministically

Sources: Claude Code transcripts (`~/.claude/projects/**.jsonl`, subagents under `<session>/subagents/agent-*.jsonl`),
hook payloads (`PreCompact`/`PostCompact` with trigger `manual|auto`, `SubagentStop` [S20]), the status line
(`context_window.used_percentage`, `current_usage` [S21]). No LLM needed for any row below.

| Metric | Definition | Existing field (`08-benchmark/lib/transcript_metrics.py@87d504f`) | Status |
|---|---|---|---|
| Peak context, parent (M04) | max over requests of input + cache_read + cache_write | `peak_context_tokens` (:372) | exists |
| Peak context per subagent (M65) | same, per `agent-*.jsonl`, compared with the role's `max_context_tokens` | `subagents.peak_context_tokens` (:385) is the max over all subagents only | extend: per agent + contract cap |
| Startup load | input + cache of the first request of a session or subagent | none | add: first `_Tokens.add` value |
| Tokens per phase | token sums between phase markers (skill invocation, `mcp__metodo__*` receipt calls, `compact_boundary`) | `tokens.main`, `tokens.subagents` (:371), `skills` (:386) are per session | add: segment by marker timestamps |
| Tool-output share | chars of `tool_result` blocks by tool name ÷ total input chars (proxy; exact tokens are not per block) | none (`tool_calls` :377 counts calls only) | add |
| Re-read ratio | Read calls whose `file_path` (+offset/limit) was already read in the same context ÷ all Read calls; also across parent and subagents | none | add |
| Subagent report size | chars of the `tool_result` answering each `Agent` call | `agent_prompt_chars` (:382) covers the brief only | add |
| Cache hit ratio (M03) | cache_read ÷ (input + cache_read + cache_write) | `cache_hit_ratio` (:373), parent only | extend to subagents |
| Compactions (M05, M66) | `compact_boundary` count, trigger, pre/post tokens | `compactions` (:394) | exists |
| Cache breakers | model switches in the parent | `model_switches` (:375) | exists |

Caveat [Inferred]: char-based shares are proxies (≈4 chars/token is an assumption); the exact per-request numbers
are only the `usage` fields. The status line value is live but not persisted unless a hook writes it.

## 6. Recommendations for the kit [Inferred]

1. **Measure before tuning.** Add to `transcript_metrics.py`: startup load, per-subagent peak vs contract cap,
   tool-output share by tool, re-read ratio, subagent report size, subagent cache hit ratio, tokens per phase (§5).
   Basis: `agent-protocol.md` §8 ("Without these figures, no protocol change gets defended") and the §5 gaps.
2. **Cap the orchestrator's window explicitly.** Set `autoCompactWindow` for the orchestrating session; start value
   300k [Assumed], tuned in Phase 2 on M04, M66 and task outcome. Basis: default ~967K [S18] vs median parent peaks
   257k-537k (Measured) vs degradation from 32K up (§2).
3. **Compact at block boundaries with a focus line**, and add a `SessionStart` hook with matcher `compact` that
   prints the active task document path, the open task ids and the last receipt id. Basis: T2, T4; existing rule
   "compact when closing each block" (`model-routing.md` Rules).
4. **Never switch model or effort mid-session in the orchestrator**; routing changes go to subagents, whose caches
   are separate. Skills that set `model:` count as a switch. Basis: T6 [S19].
5. **Filter verbose tool output with hooks** (test runners → failures; logs → matching lines) and keep the full
   output in a file whose path is returned. Basis: T10 [S13][S20].
6. **Keep startup load small and measured**: each instruction file < 200 lines (CLAUDE.md, AGENTS.md; Codex caps at
   32 KiB), `SKILL.md` < 500 lines with key rules first, one level of progressive disclosure. Basis: T9, T4.
7. **Prefer scripts/CLI and deferred MCP; one MCP server per role at most.** Basis: T8 [S9][S13].
8. **Delegate only verbose, self-contained or read-only-breadth work**; keep dependent write chains in one context.
   Basis: A1 [S11][S3] and `odd/research/model-router/methods.md` §2.
9. **Subagent report cap: 2,000 tokens (~8,000 chars) of JSON**; anything larger goes to a handoff file and the
   report returns its path and sha. Basis: A3 [S1][S2], `agent-protocol.md` §4.
10. **Briefs pass what the parent already read** (paths + line ranges) and the reading scope, to cut duplicate reads;
    measure with the re-read ratio. Basis: A2 [S11][S2].
11. **Set `omitClaudeMd: true` on kit roles** whose rules live in their contract, and test that no required rule is
    lost. Basis: A4 [S11].
12. **Enforce `max_context_tokens`, not only `max_tool_calls`**: at least a post-run check from transcripts that
    turns an over-cap subagent into a protocol finding, and optionally a per-role `autoCompactWindow` ≥ 100k.
    Basis: A6, `budget.py:25`, `model-routing.md` ("Exceeding its cap is a protocol finding").
13. **Do not trust in-context reminders for "done"**: requirements fade over long horizons; use a deterministic
    external checklist (feeds C4). Basis: A9 [S34][S37].
14. **Tool-result clearing**: rely on Claude Code's built-in clearing; for kit-owned API agents use
    `clear_tool_uses` with `clear_at_least` so cache breaks pay for themselves. Basis: T5 [S6][S33].

## 7. Sources (read 2026-10-18 with `curl -sL`; status = HTTP status of the final URL; copies in `$TMPDIR/c1ctx`)

| Id | Source and URL | Published | Status |
|---|---|---|---|
| S1 | Anthropic, Effective context engineering for AI agents, anthropic.com/engineering/effective-context-engineering-for-ai-agents | 2025-09-29 | 200 |
| S2 | Anthropic, How we built our multi-agent research system, anthropic.com/engineering/multi-agent-research-system | 2025-06-13 | 200 |
| S3 | Cognition, Don't Build Multi-Agents, cognition.ai/blog/dont-build-multi-agents (→ cognition.com) | 2025-06-12 | 200 |
| S4 | Claude docs, Context windows, platform.claude.com/docs/en/build-with-claude/context-windows.md | undated | 200 |
| S5 | Claude docs, Compaction overview (beta `compact-2026-09-04`), …/build-with-claude/compaction.md | undated | 200 |
| S6 | Claude docs, Context editing, …/build-with-claude/context-editing.md | undated | 200 |
| S7 | Claude docs, Memory tool, …/agents-and-tools/tool-use/memory-tool.md | undated | 200 |
| S8 | Claude docs, Prompt caching, …/build-with-claude/prompt-caching.md | undated | 200 |
| S9 | Claude docs, Tool search tool, …/agents-and-tools/tool-use/tool-search-tool.md | undated | 200 |
| S10 | Claude docs, Pricing (long-context: only Haiku 5.5 over 100k), …/about-claude/pricing.md | undated | 200 |
| S11 | Claude Code, Subagents, code.claude.com/docs/en/sub-agents.md | undated | 200 |
| S12 | Claude Code, Memory (CLAUDE.md), code.claude.com/docs/en/memory.md | undated | 200 |
| S13 | Claude Code, Costs, code.claude.com/docs/en/costs.md | undated | 200 |
| S14 | Claude Code, Best practices, code.claude.com/docs/en/best-practices.md | undated | 200 |
| S15 | Claude Code, Skills, code.claude.com/docs/en/skills.md | undated | 200 |
| S16 | Claude Code, Context window, code.claude.com/docs/en/context-window.md | undated | 200 |
| S17 | Claude Code, MCP, code.claude.com/docs/en/mcp.md | undated | 200 |
| S18 | Claude Code, Model config (auto-compact window), code.claude.com/docs/en/model-config.md | undated | 200 |
| S19 | Claude Code, Prompt caching, code.claude.com/docs/en/prompt-caching.md | undated | 200 |
| S20 | Claude Code, Hooks, code.claude.com/docs/en/hooks.md | undated | 200 |
| S21 | Claude Code, Status line, code.claude.com/docs/en/statusline.md | undated | 200 |
| S22 | OpenAI, Compaction, developers.openai.com/api/docs/guides/compaction (`compact_threshold`) | undated | 200 |
| S23 | OpenAI, Conversation state, developers.openai.com/api/docs/guides/conversation-state | undated | 200 |
| S24 | Codex, AGENTS.md, developers.openai.com/codex/guides/agents-md (→ learn.chatgpt.com) | undated | 200 |
| S25 | Codex, Config reference, developers.openai.com/codex/config-reference (→ learn.chatgpt.com) | undated | 200 |
| S26 | Google, Gemini long context, ai.google.dev/gemini-api/docs/long-context | updated 2026-10-15 | 200 |
| S27 | Google, Gemini context caching (implicit, min 4,096 tokens on Gemini 4 Argon), ai.google.dev/gemini-api/docs/caching | updated 2026-10-13 | 200 |
| S28 | Liu et al., Lost in the Middle, arxiv.org/abs/2307.03172 | 2023-07-06 | 200 |
| S29 | Modarressi et al., NoLiMa, arxiv.org/abs/2502.05167 | 2025-02-07 | 200 |
| S30 | Hsieh et al., RULER, arxiv.org/abs/2404.06654 | 2024-04-09 | 200 |
| S31 | Chroma, Context Rot, research.trychroma.com/context-rot (→ trychroma.com/research/context-rot) | 2025-07-14 | 200 |
| S32 | Context Length Alone Hurts LLM Performance Despite Perfect Retrieval, arxiv.org/abs/2510.05381 | 2025-10-06 | 200 |
| S33 | The Complexity Trap (observation masking), arxiv.org/abs/2508.21433 | 2025-08-29 | 200 |
| S34 | When and How Context Rot Appears in Coding Agents, arxiv.org/abs/2607.17937 | 2026-07-20 | 200 |
| S35 | Is Progressive Disclosure All You Need for Long-Context Agents?, arxiv.org/abs/2607.17598 | 2026-07-20 | 200 |
| S36 | Diagnosing and Mitigating Context Rot in Long-horizon Search, arxiv.org/abs/2606.29718 | 2026-06-29 | 200 |
| S37 | HANDBOOK.md benchmark, arxiv.org/abs/2607.25398 | 2026-07-28 | 200 |
| S38 | Context Rot in AI-Assisted Software Development, arxiv.org/abs/2606.09090 | 2026-06-08 | 200 |
| S39 | ARC, Addressable Recall Compaction, arxiv.org/abs/2607.25066 (not cited above; same idea as T7/T11) | 2026-07-27 | 200 |
| S40 | OpenCode, Config (`compaction.auto`, `prune`), opencode.ai/docs/config/ | undated | 200 |
| S41 | Gemini CLI, configuration reference, raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/reference/configuration.md | undated | 200 |
| S42 | pi, compaction.md, raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/docs/compaction.md | undated | 200 |

Kit evidence at `87d504f`: `08-benchmark/reports/phase1-findings.md:23-49,94`, `08-benchmark/METRICS.md:38-44,107-108`,
`08-benchmark/lib/transcript_metrics.py:371-394`, `03-tools/hooks/budget.py:25`, `00-principles/agent-protocol.md`,
`00-principles/model-routing.md`. arXiv 2026 items are preprints, not peer-reviewed; S34 is n=10 per arm.
Quote check (2026-10-18, `$TMPDIR/c1ctx/quotecheck.py`, whitespace/markdown-link/curly-quote normalized): 63 of 63
source quotes found in the fetched text; the 3 kit quotes in §6 found by `grep -F` in the working tree.
