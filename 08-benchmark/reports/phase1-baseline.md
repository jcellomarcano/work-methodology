# Phase 1 baseline (retrospective)

Retrospective, correlational evidence: task mix, model versions and the user's own practice drift over the period, so every delta below is a hypothesis for Phase 2, not a causal claim. Cells show the median across sessions with n; labels follow `METRICS.md`.

## Inputs

| File | Status | Tool sha256 |
|---|---|---|
| sessions.json | ok | 6f10acc8c0a0 |
| git.json | ok | 6531ef2b3f69 |
| engram.json | ok | fadb3cb90390 |
| kit.json | ok | dbb4a16c9c42 |

Sessions in scope: 110.

## Adoption boundary per project

| Project | Adoption (earliest strong kit marker) | First marker | Installer file mtime | Sessions | Kit sessions | Label |
|---|---|---|---|---|---|---|
| AndroidStudioProjects | none | — | — | 1 | 0 | Inferred |
| project-e | none | — | — | 1 | 0 | Inferred |
| project-b | 2026-09-05 | subagent:generic-judge | 2026-09-05 | 7 | 1 | Inferred |
| project-c | none | — | 2026-09-05 | 1 | 0 | Inferred |
| home | none | — | — | 1 | 0 | Inferred |
| project-f | 2026-10-02 | subagent:generic-proposer | — | 1 | 1 | Inferred |
| metodologia-de-trabajo | none | — | — | 3 | 0 | Inferred |
| project-a | 2026-09-07 | subagent:generic-cartographer | 2026-09-23 | 85 | 47 | Inferred |
| scratch-2026-09-27-93b11d | none | — | — | 1 | 0 | Inferred |
| scratchpad | none | — | — | 3 | 0 | Inferred |
| tmp.xzJE2Pxc9A | none | — | — | 1 | 0 | Inferred |
| project-d | 2026-09-11 | subagent:generic-confrontador | 2026-09-30 | 5 | 2 | Inferred |

Strong markers: a kit hook run, a `mcp__metodo__*` call, a `generic-*` subagent. Kit-named skills are weak markers (user-level skills share the names) and never set the boundary. Sessions that were resumed across the boundary are reported as `spanning` and excluded from both sides.

## project-b: before vs after

Spanning sessions excluded: 1.

| Metric | Before (n=6) | After, kit (n=0) | After, no kit (n=0) | Label |
|---|---|---|---|---|
| M01_input_tokens | 26,197,530 (n=6) | — | — | Measured |
| M02_output_tokens | 112,179 (n=6) | — | — | Measured |
| M03_cache_hit_ratio | 0.976 (n=6) | — | — | Measured |
| M04_peak_context | 280,770 (n=6) | — | — | Measured |
| M05_compactions | 0 (n=6) | — | — | Measured |
| M07_subagent_token_share | 0.028 (n=6) | — | — | Measured |
| M10_final_reply_chars | 3,438 (n=6) | — | — | Measured |
| M15_human_prompt_chars | 1,931 (n=6) | — | — | Measured |
| M15_human_prompts | 2 (n=6) | — | — | Measured |
| M11_reply_to_prompt_ratio | 1.476 (n=6) | — | — | Measured |
| M12_first_response_s | 17.862 (n=6) | — | — | Measured |
| M13_turn_wall_clock_s | 919.794 (n=4) | — | — | Measured |
| M14_tool_calls_per_turn | 57.5 (n=6) | — | — | Measured |
| M50_engram_save_calls | 0 (n=6) | — | — | Measured |
| M51_engram_recall_calls | 0 (n=6) | — | — | Measured |
| M60_subagent_runs | 0.5 (n=6) | — | — | Measured |
| M72_hook_metodo_runs | 0 (n=6) | — | — | Measured |
| cost_usd | — | — | — | Measured |
| duration_s | 3,880 (n=6) | — | — | Measured |
| M08_requests_by_model | {"claude-fable-5": 1964, "claude-opus-4-8": 346, "claude-opus-5": 1305} | {} | {} | Measured |
| M63_effort_levels_where_present | {"high": 131, "xhigh": 2330} | {} | {} | Measured |
| M60_agent_types | {"Explore": 18, "Plan": 4, "general-purpose": 141, "unknown": 32} | {} | {} | Measured |
| M80_skills_invoked | {"artifact-design": 3, "design-tokens-android": 2, "design-tokens-ios": 3, "kmp-conventions": 3, "testing-with-fakes": 1} | {} | {} | Measured |

## project-a: before vs after

Spanning sessions excluded: 4.

| Metric | Before (n=31) | After, kit (n=45) | After, no kit (n=5) | Label |
|---|---|---|---|---|
| M01_input_tokens | 26,398,397 (n=31) | 13,567,514 (n=45) | 17,018,415 (n=5) | Measured |
| M02_output_tokens | 129,253 (n=31) | 63,159 (n=45) | 120,189 (n=5) | Measured |
| M03_cache_hit_ratio | 0.963 (n=31) | 0.971 (n=44) | 0.939 (n=5) | Measured |
| M04_peak_context | 352,818 (n=31) | 256,528 (n=45) | 380,653 (n=5) | Measured |
| M05_compactions | 0 (n=31) | 0 (n=45) | 0 (n=5) | Measured |
| M07_subagent_token_share | 0.157 (n=31) | 0.29 (n=44) | 0 (n=5) | Measured |
| M10_final_reply_chars | 2,519 (n=30) | 1,621 (n=43) | 3,373 (n=5) | Measured |
| M15_human_prompt_chars | 166.25 (n=30) | 102.5 (n=44) | 674.5 (n=5) | Measured |
| M15_human_prompts | 7 (n=31) | 5 (n=45) | 1 (n=5) | Measured |
| M11_reply_to_prompt_ratio | 1.225 (n=30) | 5.822 (n=44) | 3.849 (n=5) | Measured |
| M12_first_response_s | 19.259 (n=30) | 6.956 (n=44) | 14.603 (n=5) | Measured |
| M13_turn_wall_clock_s | 569.552 (n=26) | 854.4 (n=41) | 1,208 (n=2) | Measured |
| M14_tool_calls_per_turn | 18.472 (n=30) | 11.675 (n=44) | 43.5 (n=5) | Measured |
| M50_engram_save_calls | 0 (n=31) | 1 (n=45) | 0 (n=5) | Measured |
| M51_engram_recall_calls | 0 (n=31) | 0 (n=45) | 0 (n=5) | Measured |
| M60_subagent_runs | 4 (n=31) | 5 (n=45) | 0 (n=5) | Measured |
| M72_hook_metodo_runs | 0 (n=31) | 1 (n=45) | 0 (n=5) | Measured |
| cost_usd | — | 18.291 (n=38) | 20.508 (n=5) | Measured |
| duration_s | 40,682 (n=31) | 17,611 (n=45) | 19,312 (n=5) | Measured |
| M08_requests_by_model | {"claude-fable-5": 3263, "claude-opus-4-8": 483, "claude-opus-5": 3366} | {"claude-fable-5-1": 1736, "claude-opus-5": 1895, "claude-opus-5-5": 2109} | {"claude-fable-5-1": 158, "claude-opus-5": 183, "claude-opus-5-5": 9} | Measured |
| M63_effort_levels_where_present | {"high": 2909, "max": 30, "xhigh": 3234} | {"high": 98, "medium": 3324, "xhigh": 2318} | {"high": 9, "xhigh": 341} | Measured |
| M60_agent_types | {"Explore": 69, "Plan": 20, "general-purpose": 43, "unknown": 36} | {"Explore": 41, "Plan": 2, "claude": 17, "claude-code-guide": 2, "fork": 2, "general-purpose": 22, "generic-adversario-puntos-ciegos": 44, "generic-cartographer": 20, "generic-comment-gate": 15, "generic-confrontador": 45, "generic-confrontador--opus-xhigh": 1, "generic-human-reviewer": 2, "generic-human-reviewer--haiku-medium": 1, "generic-judge": 43, "generic-mechanic": 18, "generic-mechanic--haiku-medium": 1, "generic-proposer": 27, "generic-proposer--opus-xhigh": 2, "generic-proposer--sonnet-high": 9, "generic-proposer--sonnet-medium": 1, "generic-style-reviewer": 5, "generic-verificador": 23, "generic-verificador--sonnet-medium": 1, "ref-adversary": 10, "ref-auditor": 9, "ref-proposer": 12, "unknown": 5} | {"Explore": 4, "Plan": 2, "claude-code-guide": 1} | Measured |
| M80_skills_invoked | {"anthropic-skills:markitdown": 2, "artifact-design": 4, "artifact-diagramming": 1, "dataviz": 1, "deep-research": 1, "engineering:code-review": 1, "schedule": 2, "vendor-bench": 1} | {"artifact-design": 5, "cartografia": 1, "chained-pr": 1, "claude-api": 1, "code-review": 6, "comentario-de-review": 3, "comentario-necesario": 1, "comment-writer": 1, "ficha-de-cambio": 1, "flow-trace": 2, "mensaje-de-pr": 3, "publicar-comentario-de-review": 2, "respuesta-humana": 1, "revision-con-recibo": 3, "revision-humana": 1, "ronda-adversarial-dos": 2} | {"artifact-design": 2, "artifact-diagramming": 2, "flow-trace": 1} | Measured |

## project-d: before vs after

Spanning sessions excluded: 1.

| Metric | Before (n=3) | After, kit (n=1) | After, no kit (n=0) | Label |
|---|---|---|---|---|
| M01_input_tokens | 534,364,212 (n=3) | 186,707,358 (n=1) | — | Measured |
| M02_output_tokens | 906,346 (n=3) | 463,134 (n=1) | — | Measured |
| M03_cache_hit_ratio | 0.969 (n=3) | 0.984 (n=1) | — | Measured |
| M04_peak_context | 996,268 (n=3) | 856,906 (n=1) | — | Measured |
| M05_compactions | 1 (n=3) | 1 (n=1) | — | Measured |
| M07_subagent_token_share | 0.016 (n=3) | 0.508 (n=1) | — | Measured |
| M10_final_reply_chars | 2,141 (n=3) | 1,822 (n=1) | — | Measured |
| M15_human_prompt_chars | 94.5 (n=3) | 132 (n=1) | — | Measured |
| M15_human_prompts | 28 (n=3) | 17 (n=1) | — | Measured |
| M11_reply_to_prompt_ratio | 2.244 (n=3) | 1.039 (n=1) | — | Measured |
| M12_first_response_s | 17.257 (n=3) | 4.149 (n=1) | — | Measured |
| M13_turn_wall_clock_s | 733.899 (n=3) | 670.648 (n=1) | — | Measured |
| M14_tool_calls_per_turn | 13.5 (n=3) | 33.471 (n=1) | — | Measured |
| M50_engram_save_calls | 0 (n=3) | 42 (n=1) | — | Measured |
| M51_engram_recall_calls | 0 (n=3) | 1 (n=1) | — | Measured |
| M60_subagent_runs | 6 (n=3) | 46 (n=1) | — | Measured |
| M72_hook_metodo_runs | 0 (n=3) | 0 (n=1) | — | Measured |
| cost_usd | — | 167.184 (n=1) | — | Measured |
| duration_s | 184,130 (n=3) | 140,640 (n=1) | — | Measured |
| M08_requests_by_model | {"claude-fable-5": 629, "claude-opus-4-8": 440, "claude-opus-5": 1251} | {"claude-opus-5-5": 456} | {} | Measured |
| M63_effort_levels_where_present | {"max": 791, "xhigh": 634} | {"high": 456} | {} | Measured |
| M60_agent_types | {"Explore": 18, "Plan": 8, "general-purpose": 41} | {"Explore": 3, "Plan": 1, "general-purpose": 1, "generic-adversario-puntos-ciegos": 6, "generic-cartographer": 2, "generic-comment-gate": 2, "generic-confrontador": 6, "generic-judge": 6, "generic-mechanic": 2, "generic-proposer": 12, "generic-verificador": 5} | {} | Measured |
| M80_skills_invoked | {"claude-api": 1} | {} | {} | Measured |

## project-b: by month of session start (trend, no boundary)

| Month | Sessions | Kit sessions | Peak context | Output tokens | Final reply chars | First response s | Subagent token share | Subagent runs | Engram recalls |
|---|---|---|---|---|---|---|---|---|---|
| 2026-07 | 5 | 0 | 253,819 (n=5) | 99,394 (n=5) | 3,646 (n=5) | 18.468 (n=5) | 0 (n=5) | 0 (n=5) | 0 (n=5) |
| 2026-08 | 2 | 1 | 982,046 (n=2) | 1,313,850 (n=2) | 1,520 (n=2) | 18.143 (n=2) | 0.437 (n=2) | 93 (n=2) | 0 (n=2) |

Label: Measured (medians per month).

## project-a: by month of session start (trend, no boundary)

| Month | Sessions | Kit sessions | Peak context | Output tokens | Final reply chars | First response s | Subagent token share | Subagent runs | Engram recalls |
|---|---|---|---|---|---|---|---|---|---|
| 2026-07 | 17 | 1 | 302,720 (n=17) | 129,253 (n=17) | 2,571 (n=17) | 22.037 (n=17) | 0.09 (n=17) | 3 (n=17) | 0 (n=17) |
| 2026-08 | 14 | 0 | 481,443 (n=14) | 205,918 (n=14) | 2,448 (n=14) | 17.428 (n=14) | 0.275 (n=14) | 6 (n=14) | 0 (n=14) |
| 2026-09 | 40 | 33 | 292,034 (n=40) | 78,456 (n=40) | 1,919 (n=37) | 9.26 (n=38) | 0.181 (n=39) | 5 (n=40) | 0 (n=40) |
| 2026-10 | 14 | 13 | 216,584 (n=14) | 43,517 (n=14) | 1,630 (n=14) | 3.962 (n=14) | 0.348 (n=14) | 1.5 (n=14) | 0 (n=14) |

Label: Measured (medians per month).

## project-d: by month of session start (trend, no boundary)

| Month | Sessions | Kit sessions | Peak context | Output tokens | Final reply chars | First response s | Subagent token share | Subagent runs | Engram recalls |
|---|---|---|---|---|---|---|---|---|---|
| 2026-07 | 1 | 0 | 996,268 (n=1) | 2,032,411 (n=1) | 1,936 (n=1) | 27.524 (n=1) | 0.561 (n=1) | 66 (n=1) | 0 (n=1) |
| 2026-08 | 2 | 0 | 544,126 (n=2) | 462,060 (n=2) | 2,201 (n=2) | 14.276 (n=2) | 0.008 (n=2) | 3 (n=2) | 0 (n=2) |
| 2026-09 | 2 | 2 | 911,448 (n=2) | 1,626,817 (n=2) | 1,579 (n=2) | 7.362 (n=2) | 0.511 (n=2) | 172 (n=2) | 0.5 (n=2) |

Label: Measured (medians per month).

## Context under multi-agent work (S22)

| Cell | n | Peak context | Compactions / session | Compactions per 1M input | Tokens dropped / compaction | Subagent token share | Agent prompt chars | Output tokens |
|---|---|---|---|---|---|---|---|---|
| kit|with_subagents | 39 | 372,845 (n=39) | 0 (n=39) | 0.005 | 938,541 (n=25) | 0.445 (n=39) | 2,873 (n=871) | 105,106 (n=39) |
| kit|without_subagents | 12 | 127,834 (n=12) | 0 (n=12) | 0 | — | 0 (n=11) | — | 9,328 (n=12) |
| no_kit|with_subagents | 38 | 537,384 (n=38) | 0 (n=38) | 0.004 | 957,246 (n=28) | 0.231 (n=38) | 3,489 (n=746) | 257,028 (n=38) |
| no_kit|without_subagents | 21 | 129,238 (n=21) | 0 (n=21) | 0 | — | 0 (n=19) | — | 24,224 (n=21) |

Label: Measured (all cells).

## Delivery (git)

| Repo | Side | Commits | Conventional rate | Code commits with tests | Merges | Lead time days (median) | Label |
|---|---|---|---|---|---|---|---|
| project-b | before (2026-09-05) | 636 | 0.984 | 0.502 | 142 | 0.001 | Measured |
| project-b | after (2026-09-05) | 143 | 0.531 | 0.8 | 0 | — | Measured |
| project-c | before (no adoption) | 167 | 0.952 | 0.3 | 0 | — | Measured |
| project-c | after (no adoption) | 0 | — | — | 0 | — | Measured |
| project-a | before (2026-09-07) | 2246 | 0.354 | 0.383 | 31 | 3.139 | Measured |
| project-a | after (2026-09-07) | 1053 | 0.881 | 0.725 | 3 | 74.026 | Measured |
| project-d | before (2026-09-11) | 119 | 0.067 | 0.639 | 0 | — | Measured |
| project-d | after (2026-09-11) | 483 | 0.031 | 0.782 | 0 | — | Measured |

## Memory (Engram)

| Project | Sessions | Zero observations | Observations | Joined to transcripts | Transcript sessions with recall | with save | save without recall | Label |
|---|---|---|---|---|---|---|---|---|
| 03-tools | 1 | 0 | 6 | 0 | 0 | 0 | 0 | Measured (counts) / Inferred (join by session UUID) |
| project-b | 4 | 2 | 12 | 1 | 0 | 0 | 0 | Measured (counts) / Inferred (join by session UUID) |
| metodologia-de-trabajo | 4 | 1 | 6 | 3 | 1 | 2 | 1 | Measured (counts) / Inferred (join by session UUID) |
| project-a | 386 | 363 | 326 | 24 | 21 | 26 | 7 | Measured (counts) / Inferred (join by session UUID) |
| scratch-2026-09-27-93b11d | 2 | 1 | 1 | 1 | 1 | 1 | 0 | Measured (counts) / Inferred (join by session UUID) |
| scratchpad | 3 | 3 | 0 | 3 | 1 | 0 | 0 | Measured (counts) / Inferred (join by session UUID) |
| project-d | 5 | 3 | 34 | 2 | 1 | 1 | 0 | Measured (counts) / Inferred (join by session UUID) |

## Kit telemetry (hooks, gates, receipts)

### 03-tools

Ledger sessions 3 (2026-09-15 → 2026-09-15), lines 4, joined to transcripts 0. Label: Measured.

| Kind:decision | Count |
|---|---|
| session-start:log | 3 |
| forbidden-path:ask | 1 |

Receipts: 0 (voids 0), by verdict {}, by state {}, captures 0.
Reply-lint rule hits: {}. Budget events: {}.

### project-a-tools

Ledger sessions 174 (2026-09-15 → 2026-10-13), lines 1410, joined to transcripts 42. Label: Measured.

| Kind:decision | Count |
|---|---|
| reply-lint:warn | 439 |
| output-invalid:warn | 187 |
| session-start:log | 183 |
| budget-deny:deny | 135 |
| gate-receipt:allow | 81 |
| budget-warn:warn | 75 |
| gate-push:warn | 53 |
| scope-outside:warn | 50 |
| gate-merge:warn | 25 |
| gate-push-outcome:ran | 25 |
| rebase:log | 25 |
| amend:log | 18 |
| gate-merge:deny | 18 |
| output-fenced:log | 18 |
| gate-merge-outcome:ran | 15 |
| gate-receipt-outcome:ran | 14 |
| gate-tag:warn | 12 |
| forbidden-path:deny | 10 |
| gate-tag-outcome:ran | 10 |
| forbidden-path:ask | 7 |
| gate-push:allow | 4 |
| output-truncated:log | 3 |
| force-push:deny | 1 |
| gate-push:deny | 1 |
| gate-tag:deny | 1 |

Receipts: 50 (voids 10), by verdict {"approved": 4, "escalated": 10, "inconclusive": 14, "none": 9, "rejected": 13}, by state {"captured": 6, "finalized": 41, "started": 3}, captures 285.
Reply-lint rule hits: {"COM-01": 6, "COM-02": 282, "COM-03": 126, "COM-05": 98, "COM-09": 14, "COM-11": 1, "COM-15": 145}. Budget events: {"generic-adversario-puntos-ciegos:budget-deny": 9, "generic-adversario-puntos-ciegos:budget-warn": 12, "generic-cartographer:budget-deny": 10, "generic-cartographer:budget-warn": 10, "generic-comment-gate:budget-deny": 8, "generic-comment-gate:budget-warn": 3, "generic-confrontador:budget-deny": 11, "generic-confrontador:budget-warn": 12, "generic-human-reviewer:budget-warn": 1, "generic-judge:budget-deny": 2, "generic-judge:budget-warn": 2, "generic-mechanic--haiku-medium:budget-warn": 1, "generic-mechanic:budget-deny": 45, "generic-mechanic:budget-warn": 8, "generic-proposer--opus-xhigh:budget-warn": 1, "generic-proposer--sonnet-high:budget-deny": 4, "generic-proposer--sonnet-high:budget-warn": 5, "generic-proposer:budget-deny": 16, "generic-proposer:budget-warn": 12, "generic-style-reviewer:budget-deny": 9, "generic-style-reviewer:budget-warn": 2, "generic-verificador:budget-deny": 21, "generic-verificador:budget-warn": 6}.


## Not measured in Phase 1

| Id | Metric | Label | Reason |
|---|---|---|---|
| M25 | Seeded-defect recall | Unknown | needs Phase 2 seeded tasks |
| M26 | False findings rate | Unknown | needs a blind judge over Phase 2 runs |
| M63 | Effort level per request | Unknown | present on a minority of transcript records only; reported as a share where present |
| M64 | Router decisions logged | Unknown | model-tiers.json is read by no code; nothing is logged |
| M83 | Transferable ways of working | Assumed | reviewer judgment, listed in the report prose |
