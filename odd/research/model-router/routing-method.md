# R6: the kit's routing method (read 2026-10-16)

Synthesis of lanes R1-R5 for `odd/tasks/model-router.md` (S2, S4). It specifies what R7 (catalog config) and R8
(deterministic router + evaluator) implement. Source keys: **[A§n]** `anthropic.md`, **[G§n]** `google.md`, **[O§n]**
`openai.md`, **[L§n]** `local.md`, **[M§n]** `methods.md` (all in this directory); **[MR]** `00-principles/model-routing.md`,
**[MPR§n]** `multi-provider-routing.md`, **[AP§n]** `agent-protocol.md`, **[RR§3]** `review-receipt.md`, **[MT]**
`03-tools/config/model-tiers.json`. Tags: [Stated] from a dossier quote, [Inferred] our design, [Unknown] open.
Prices are USD/MTok, standard tier, and expire.

**Spot-check of the two dossiers whose workers crashed** (fetched 2026-10-16 with `curl -sL` into `$TMPDIR/r6check`):
- `openai.md`: 6/6 quotes found verbatim. Five on the first fetch: S2 6.1 Sol "The `none` and `minimal` reasoning
  efforts are not supported."; S8 "Treat `reasoning.effort` as a tuning knob…"; S14 "If a custom agent file sets
  `model` or `model_reasoning_effort`, the value in the file takes precedence."; S12 "…`max`, or `ultra`. Available
  levels depend on the model and client."; S7 "keep the lightest setting that meets your quality bar.". "Batch and Flex
  are priced at 50% of Standard rates." is on the S2 Astra, 6 Sol and 6 Luna pages, not on S3 (the dossier cites both).
  S2 prices Astra $10/$50, 6.1 Sol $2/$10, 6 Luna $0.10/$0.50 also match.
- `local.md`: 6/6 quotes found: S22 Qwen3.8 "Thinking mode is on by default and can be disabled per request"; S7 "…should
  be set to at least 64000 tokens."; S6 "Required RAM will scale by OLLAMA_NUM_PARALLEL * OLLAMA_CONTEXT_LENGTH."
  (split by markup); S20 "doesn’t support routing Claude Code to non-Claude models through any gateway"; S28 "The
  reasoning level can be set in the system prompts"; S9 "Use a context window of at least 64k tokens for Codex.";
  S11 has `--reasoning-effort`. **One claim fails:** S9 shows `codex --oss -m gpt-oss:120b`, not `gpt-oss:20b`;
  only the `codex --oss -m <tag>` pattern is used. S10 shows `ollama launch pi` without `--model`; not used.

## 1. Decision summary

1. **Routing becomes computed.** A script maps task facts to a roster (role, tier, model, effort, launch, mode).
   Static `model:` frontmatter stays only as a generated fallback. Today no code reads `model-tiers.json`, no effort
   is set and nothing logs routing (S1; [M§1] K1 §6).
2. **Effort is set explicitly per role.** It is a separate lever from model choice and controls all output tokens
   ([A§2]: "affects **all tokens**"). Today it runs unset: 3,304 of 5,917 requests ran at `medium` (K1 §0.1, [M§3]).
3. **Deterministic first-match table, no LLM router.** Learned routers fall to random-router level on
   out-of-distribution tasks, and the kit has no labelled data yet ([M§1], RouteLLM).
4. **Escalate one step at a time: effort first, then tier.** Raise effort for diligence failures. Raise the tier when
   the answer is wrong with full context ([A§2] S14; [M§3]; [O§2] "tuning knob").
5. **Cheap first, escalate on failure, but only behind an external verifier** (schema, `cite_check.py`, tests).
   Anthropic measured ≈97% at ≈$0.17 against $0.29 for all-`high` ([A§2] S12). Self-verification is noisy ([M§1]).
6. **Launch little.** No review subagent below the medium RDD tier. Parallel only for read-only roles. Writes and
   dependent chains stay in one agent. Max 3 in parallel, depth 1 ([M§2], [M§5]; [A§4]; [O§4]; [G§3] no nesting).
7. **Best result = lexicographic, not weighted.** First every mandatory role of the tier, then the quality guards,
   then the cheapest roster under budget. Budget never removes a mandatory role ([M§4]; [RR§3]).
8. **Catalog refresh.** The owner admitted the Claude 5.5 family by decision (L5, cost), not by the [MPR§4] test:
   Haiku, Sonnet and Opus 5.5 replace Haiku 4.5, Sonnet 5 and Opus 5, and Opus 5.5 becomes the orchestrator. The
   new Google, OpenAI and local models still enter as `candidate` ([MPR§4]).
9. **Prices carry dates, and the router takes `as_of` as an input** (never the system clock). Argon doubles on
   2026-12-01 and the Flash tiers on 2027-01-01 ([G§1]).
10. **Every decision writes one log line** so cost and quality per tier can be attributed ([M§4]; §5 below).

## 2. Model catalog proposal (A = admitted incumbent, C = candidate)

Effort column order: small = verdict / mechanic; medium = cartographer / proposer / verifier & judge; large =
default / critical path at the high tier.

| Tier | Anthropic | Google | OpenAI | Local (offline/privacy only) |
|---|---|---|---|---|
| small | A `claude-haiku-5-5` low / medium, $0.10/$0.50 for prompts ≤100K (owner decision L5) [A§1,§5]; legacy `claude-haiku-4-5` | C `gemini-3.5-flash-lite` minimal / medium, $0.30/$2.50 [G§1,§5] | C `gpt-6-luna` low / high, $0.10/$0.50 [O§1,§5] | C `qwen3.5:9b`, `gemma4:12b-it`, `gpt-oss:20b` with thinking off / low [L§1,§4] |
| medium | A `claude-sonnet-5-5` medium / medium / high, $2/$10 (owner decision L5) [A§1,§5]; legacy `claude-sonnet-5` | C `gemini-3.8-flash` low→medium / medium / medium, $0.75/$3.75 until 2026-12-31 [G§1,§5] | C `gpt-6-luna` high (cartographer); `gpt-6.1-sol` medium (proposer, verifier, judge), $2/$10 [O§5] | C only: 24-36B at Q4 with 64K context (e.g. `qwen3.8:27b-q4_K_M`), never measured here [L§2,§4] |
| large | A `claude-opus-5-5` high / xhigh, $4/$20 (owner decision L5) [A§1,§5]; legacy `claude-opus-5` | C `gemini-4-argon` high, $2/$10 → $4/$20 from 2026-12-01 [G§0,§5] | C `gpt-6-astra` high, $10/$50; cheaper trial `gpt-6.1-sol` xhigh [O§5] | none: "Not a fit" [L§4] |
| orchestrator | A `claude-opus-5-5` high, $4/$20 (owner decision L5; Anthropic: matches Fable "for about a fifth of the cost per solved task" [A§5]); `claude-fable-5-1` $10/$50: an owner-approved escalation only (L6) | C `gemini-4-argon` medium, not through Gemini CLI [G§5] | C `gpt-6-astra` medium [O§5] | none [L§4] |

Catalog rules for R7 [Inferred]:
- Replace the stale candidates in [MT]: `gemini-3.1-pro-preview` becomes `gemini-4-argon` ([G§1]: GA vs preview).
  `gpt-5.4-*` and `gpt-5.6-*` become GPT-6 entries ([O§1]: previous generation; [MT]'s 5.6 Sol price was wrong).
- Each entry: `price_schedule: [{from, usd_in, usd_out}]`, `read`, `effort_levels`, `harness_ids`, `status`.
- Effort ladders: Anthropic `low…max`; `budget_tokens` returns 400 on 4.7+ ([A§1]). Gemini 3.8 Flash `low…high`,
  `minimal` errors ([G§1]). Argon `low…high` ([G§2]). GPT-6 `none…max`, with `none` rejected on Astra and 6.1 Sol
  ([O§2]). Local is per model: on/off, low/medium/high, or `Reasoning strength` ([L§1]).
- Local Codex 0.154.0 lacks `gpt-6.1-sol` and `gpt-6-luna`: their Codex ids stay [Unknown] until a run ([O§3]).

## 3. Deterministic decision table

**Inputs** (all computed without an LLM; producer in parentheses, per [M§4]):
`tier`, `reasons`, `lens_focus`, `owner_gate` (`rdd_risk.derive`) · `lane` opus|sonnet|none (`change_card_validator`) ·
`critical_hit` (shared build or `money_paths` in `reasons`) · `changed_lines`, `modules`, `languages` (diff facts) ·
`test_sectors`, `full_required` (`test_sectors.py`) · `task_kind` review|implement|map|comment|docs (invoking skill) ·
`map_age_days` · `budget_usd` (card, new field) · `offline` · `admitted` (catalog) · `as_of` (date) · `prior`:
`truncated`, `schema` PASS|FAIL, `verdict`, `findings`, `p0_from_tier`, `disagreement`, `stalls`.

**Guards** (run first; any hit → `status: error`, fail closed): unknown `task_kind`; missing `tier`; `lane=opus` with
`tier≠high` (rdd_risk maps opus to high, so a mismatch means stale input); `full_required` with `tier≠high` ([RR§3]
"bumps the layer to high").

**Rows (first match wins).** P-rows react to the previous step and are checked before the base rows. Notation:
role tier/effort.

| Id | Condition | Roster → launch / mode | Max fan-out |
|---|---|---|---|
| P1 | `prior.stalls ≥ 2` on this step | none; `status: owner` ([MR] "two stalls") | 0 |
| P2 | `prior.truncated` | same role, same tier/effort, scope split by module; once ([AP§2]) | 3 |
| P3 | `prior.schema=FAIL` | same role, effort +1; a second FAIL → tier +1 ([M§3] diligence) | 1 |
| P4 | `prior.p0_from_tier ∈ {small, medium}` | same role, one tier up, to confirm the P0 before it counts ([MR]) | 1 |
| P5 | `prior.disagreement` between adversaries | judge large/high; large/xhigh if `critical_hit` ([M§4] D6) | 1 |
| P6 | `prior.verdict=FAIL` from the verifier | proposer again, same tier/effort, once; second FAIL → P1 ([M§4] D3) | 1 |
| B0 | `tier=exempt` (any kind) | skip all subagents; scripts only (`docs_lint`) ([RR§3]) | 0 |
| B1 | `tier=low`, or `task_kind=comment` | scripts (contract, `comment_gate.py`); comment-gate small/low only if new comments > 0 | 1 |
| B2 | `task_kind=map` | cartographer per module: small/medium if `modules=1` (scoped run measured at 26-30k [MR]), else medium/medium; parallel | 3, then batches |
| B3 | `implement`, `tier=medium` | cartographer medium/medium only if `map_age_days>7` or no map ([MR]); proposer medium/medium, then verifier medium/high; sequential | 1 |
| B4 | `implement`, `tier=high` | as B3, with proposer medium/high; after the verifier, run B6 on the diff | 1 |
| B5 | `review`/`docs`, `tier=medium` | challenger medium/high with `lens_focus` + sector verifier medium/medium, parallel; judge medium/high only if `findings>0` ([RR§3]) | 2 |
| B6 | `review`/`docs`, `tier=high` | owner consent first; challenger and blind-spot adversary large/high (xhigh if `critical_hit`), parallel; verifier medium/high; judge medium/high, large/xhigh on a P0 or critical property ([RR§3]; [M§5]) | 2 (+1 trial) |
| B7 | none of the above | `status: error` (fail closed) | 0 |

**Model resolution**, per roster entry [Inferred]: the provider order comes from the `admitted` entries for the role's
tier, in catalog order. Today that is Anthropic only. A `candidate` fills only the B6 trial slot: one third adversary
from another provider, tagged `trial`, rated by a blind judge ([MPR§2]; [M§5] rule 8; cross-family judge bias [M§1]).
The proposer stays on the incumbent until a low-risk trial ([MPR§2]). The availability fallback is the next admitted
model, at most 3 ([A§3] `--fallback-model`).

**Post-passes** (in order, after the row):
1. **Offline**: if `offline=true`, keep only local admitted models. A mandatory role with no admitted local model →
   `status: blocked`, never a silent remote call ([M§4] D7). Ollama `:cloud` tags are remote ([L§1]).
2. **Budget**: estimated cost > `budget_usd` → drop optional roles in this fixed order: trial adversary, then the
   judge on zero findings, then the stale-map cartographer. Mandatory roles ([RR§3] per tier; proposer and verifier for
   `implement`) are never dropped. If still over budget → `status: over_budget`; the owner decides ([M§4] D8).

**Escalation ladder** (one step per launch; effort is fixed per agent session because changing it invalidates the
prompt cache [A§2]):
1. Diligence failure (truncated, schema FAIL, `not_covered`, tests skipped) → effort +1 on the same model, once.
2. Wrong with full context, or step 1 failed → tier +1 at that role's default effort ([A§2] S14; [M§3]).
3. Ceiling: large/xhigh. `max` is never automatic ([A§2] "prone to overthinking"; [O§2] `xhigh` "Only use when your
   evals show a clear benefit"). If the next level is missing from the model's ladder, move up a tier instead.
4. A critical finding from a lower tier is confirmed one tier up (P4). Two stalls → owner (P1).
5. No voting or sampling without an automatic verifier ([M§1] voting is non-monotone and plateaus).

## 4. "Best result" made operational

Objective, in lexicographic order ([M§4]):
1. Coverage: every mandatory role of the RDD tier is present.
2. Quality guards: verify above, escalate on truncation, schema FAIL or disagreement, and keep a real verifier
   ([M§2] MAST: verification failures 8.2% + 9.1%).
3. Cost: the cheapest roster that satisfies 1 and 2 under `budget_usd`.

Quality is never traded for cost at the high tier; extra roles earn their place only on risk (K2 pilot: 7 valid
findings for $8.38 vs 6 for $1.34 vanilla, [M§2]).

Evaluator (R8), deterministic, scored against fixtures `tests/fixtures/router/*.json` ([M§4]):
- **Roster correctness**: exact match on (role, tier, model, effort, launch, mode) against the expected roster. Effort
  correctness is reported per role.
- **Under-provisioning**: count of missing mandatory roles. It must be 0, and any value above 0 fails the run.
- **Over-provisioning**: estimated cost ÷ cost of the minimal correct roster. Cost = Σ tokens_in × usd_in +
  tokens_out × usd_out, with prices from the catalog schedule at `as_of`. Token estimates are seeded from kit
  measurements and capped at `max_context_tokens`: cartographers 96-110k ([MPR§2]), large adversaries 106-146k, scoped
  small cartography 26-30k ([MR]).
- **Rule coverage**: every row P1-B7, every guard and both post-passes fired by at least one fixture. Boundaries
  included: `changed_lines` = `low_max_changed_lines` and +1, no card, shared build touched, offline with and without a
  local model, and the `as_of` dates on either side of 2026-12-01.
- **Negative controls**: the same input gives byte-identical output; shuffled paths give the same output; a
  `candidate` is never chosen outside the trial slot; offline never yields a remote provider; an unknown kind fails
  closed.

Phase 2 recalibration [Inferred]: the log (§5) joined with run outcomes yields cost per valid finding, per tier and per
effort, which answers H6 (static vs all-opus, K1 §6 via [M§4]). Recalibration edits only config: effort defaults,
token estimates and the optional-role order. It bumps the catalog version and updates the fixtures in the same change.
Every vendor applies the same tuning rule: pick the lowest level that meets the quality bar ([G§2], [O§2], [A§4] "Tune
one model before you add a second"). A learned router waits for labelled kit data ([M§1]).

## 5. What the router writes

One JSONL line per decision, appended to `runs/routing.jsonl`, next to the cost logs that admission already writes to
`runs/` ([MPR§4]). Router stdout stays timestamp-free, so the output remains byte-identical; the logger adds `ts`.

`{decision_id, ts, router_version, catalog_version, catalog_sha256, inputs_hash, inputs, guard, rule_id, post_passes,
roster: [{role, tier, provider, model, effort, launch, mode, fanout, trial}], est_cost_usd, budget_usd, status}`

- `inputs_hash` = sha256 of canonical input JSON (sorted keys and sets); `decision_id` = hash + `prior` step number.
- After each launch the orchestrator appends `{decision_id, role, model, effort, tokens_in, tokens_out, cost_usd,
  truncated, schema, verdict}`. That closes the phase1-findings §6 gap: per-request model and effort become
  attributable to quality ([AP§8] requires per-run figures).

## 6. Harness mapping (roster entry → launch)

- **Claude Code** [A§3]:
  - Model and effort: subagent frontmatter `model: <full id>` + `effort: low|medium|high|xhigh|max`, or the
    per-invocation `model` / `effort` params (v2.1.292+). Pin full ids, because a same-family alias collapses to the
    main session's model.
  - Things that silently override the router: `CLAUDE_CODE_EFFORT_LEVEL` beats frontmatter, so never export it. Under
    `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` frontmatter is ignored, so the installer must refuse it. `maxEffortLevel` caps
    effort.
  - Thinking is inherited (no per-subagent setting). Session: `claude --model <alias> --effort <level>`.
- **pi** [O§3][G§3][L§3]:
  - Syntax: `pi --model <provider>/<id>:<thinking>`, e.g. `openai-codex/gpt-6.1-sol:high`, `google/gemini-4-argon:high`.
    Levels are `off…max`, "clamped to the model's capabilities".
  - Unverified: pi's level mapping onto Google/OpenAI values; Argon max output (pi 32.8K vs Google 65,536); Anthropic
    ids in pi (no dossier). Local: `models.json` provider (`http://localhost:11434/v1`), `pi --model ollama/<tag>`.
- **Codex CLI** [O§3]:
  - Per role: `.codex/agents/<role>.toml` with `name`, `description`, `developer_instructions`, `model`,
    `model_reasoning_effort`. Fallbacks: `[agents] default_subagent_model`, `default_subagent_reasoning_effort`,
    `max_concurrent_threads_per_session`.
  - Headless `codex exec -m <id>`; `-c model_reasoning_effort='"high"'` is [Inferred]. Never `ultra` (auto-delegation).
    Sandbox and MCP come from the parent, so the [MPR§3] per-agent sandbox row is wrong.
- **Gemini CLI** [G§3]:
  - `.gemini/agents/<role>.md` with `model:`. `/model` and `--model` do not override subagents.
  - The frontmatter has no thinking key. Per-agent thinking = `modelConfigs.overrides` + `match.overrideScope` +
    `generateContentConfig.thinkingConfig.thinkingLevel` ([Inferred], not run).
  - Argon: "not optimized" in Gemini CLI; use the API or pi. Headless: `gemini -p <prompt> -m <id>`.
- **Local runtimes** [L§3]:
  - Ollama: `/api/chat` with `"think": "low"` and `"options": {"num_ctx": 65536}` (at least 64K for agents). OpenAI
    route: `/v1` with `reasoning_effort`.
  - Others: `llama-server --reasoning-effort LEVEL -c N`; LM Studio `/v1/responses` `"reasoning": {"effort": "low"}`;
    Codex `codex --oss -m <tag>`.
  - Claude Code over `ANTHROPIC_BASE_URL` works but Anthropic does not support it: avoid for kit roles.

## 7. Open decisions for the owner

1. **[Decided L5: Opus 5.5] Orchestrator: Fable 5.1 or Opus 5.5?** Anthropic measured Opus 5.5 matching Fable "for about a fifth of the cost
   per solved task" ([A§5]). *Rec.:* keep Fable admitted; run Opus 5.5 through the §4 admission test; the owner decides.
2. **[Decided L5: yes, now] Incumbent refresh to the 5.5 family.** *Rec.:* first run the admission test on Haiku 5.5 (Haiku 4.5's retirement
   date has passed, [A§1]), then Sonnet 5.5 and Opus 5.5. No fast-track: [MPR§4] stays the law.
3. **Router authority.** *Rec.:* the router is authoritative at launch (R9). Frontmatter is generated from admitted
   catalog defaults and is used only when the router has not run.
4. **Budget field in the change card.** *Rec.:* add an optional `Budget (USD)`. When absent, no pruning happens and no
   `over_budget` status is raised.
5. **Offline flag source.** *Rec.:* `project.json` `offline: true` OR env `METODO_OFFLINE=1`; either one wins.
6. **Fan-out cap.** *Rec.:* 3 in parallel, depth 1, well below Claude Code's default 20 ([A§3]): "most coding
   tasks involve fewer truly parallelizable tasks than research" ([A§4]).
7. **Trial slot.** *Rec.:* off by default; on per project only at the high tier when `budget_usd` allows it.
8. **Local scope.** *Rec.:* admit local models only to the small tier, and only for offline or privacy repos ([L§4]).
   Admission requires a real run on this M1 Max, because throughput and tool reliability are [Unknown] ([L§5]).
9. **Google large candidate.** *Rec.:* Argon replaces 3.1 Pro preview. Trial it through the API or pi before its
   2026-12-01 price doubling ([G§1,§3]).
10. **Routing log location.** *Rec.:* `runs/routing.jsonl`, with the same retention as the existing `runs/` logs.
