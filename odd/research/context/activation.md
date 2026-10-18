# Activation policy · which kit elements are ON for a task (research C3)

Feature `odd/tasks/context-optimization.md` S1, S4; research only. Kit citations are `path:line@44bd74c`;
`router.py` and `model-tiers.json` are being edited by a parallel worker (working-tree line numbers).

**Answer.** Most of the kit's cost is (a) 57-89 ms per hook run (42 ms is Python startup), one PreToolUse
and one PostToolUse run per tool call, and (b) text that is always in context: skill and agent listings
and the session banner. Most of its value is in a few blocking guards. The `warn` mode is a silent ledger
line the agent never sees, so nothing can act on it: `reply_lint` logged 439 FAILs and changed nothing it
could observe. The policy computes a profile from facts; the profile turns each element OFF, LOG, WARN or
BLOCK; a ledger report proposes promotions and demotions against thresholds kept in config [Inferred].

## 1. Inventory: cost and protection

Latency: median of 7 runs on this machine (macOS) with representative stdin, `METODO_HOOKS_DIR` in the temp
dir; bare `python3 -c pass` is 42 ms [Measured]. Tokens = chars/4 [Assumed ratio]. FP = false positive.

| Element | Fires on | Context cost | Latency | What it protects, with evidence |
|---|---|---|---|---|
| `budget.py` (absolute) | every PreToolUse, matcher `""` (`hooks.settings.json:9`) | 0; a deny adds 1 line | main session 57 ms (exits at once), subagent 71 ms | runaway subagents: 135 deny, 75 warn (phase1 §3) [Measured]; quality after a deny is unknown (H3) |
| `guard_paths.py` absolute part | PreToolUse Edit/Write/MultiEdit | 0 unless deny/ask | 89 ms (subagent Edit) | build files and `.claude/`: 10 deny, 7 ask (phase1 §4) [Measured] |
| `guard_paths.py` scope (warn/block) | same, subagents only (`guard_paths.py:38`) | 0 in warn mode | same run | out-of-scope edits: 50 warns, all invisible to the agent (`guard_paths.py:55-56`) [Measured] |
| `guard_gates.py` absolute part | PreToolUse Bash and receipt MCP tools | 0 unless deny | 57 ms (`ls`) | force push 1 deny, subagent merge 18 deny (phase1 §4) [Measured] |
| `guard_gates.py` push/PR gate | same, main session, no approved receipt | 0 warn / 1 line ask | same run | delivery without review: gate-push warn 53, allow 4, deny 1 [Measured] |
| `guard_gates.py` PostToolUse | every Bash | 0 | ~57 ms | logs only (`guard_gates.py:132-134`) |
| `touched_paths.py` | PostToolUse Edit/Write | 0 | 71 ms | input for the review tier (touched set) |
| `session_start_status.py` | startup, resume, compact, clear | 260 B ≈ 65 tok each time | 87 ms | tells the agent the RDD mode and tree |
| `reply_lint.py` | Stop, main session, reply ≥ 400 chars | 0: ledger only, nothing printed (`reply_lint.py:34-37`) | 62 ms | COM rules: 439 FAILs logged as warn, 0 blocks, no fix evidence (phase1 §4, §10 "unsupported so far") |
| `validate_subagent_output.py` | SubagentStop of roles with a schema (frontmatter) | 0 warn; a block costs one more subagent turn | not measured | parseable captures; on pi it can only log (`validate_subagent_output.py:8-11`) |
| 11 roles (`01-roles/agents/`) | when launched | descriptions 1,590 chars ≈ 0.4k tok always loaded; each body loads only in its own subagent | one subagent per run | judge 43, challenger 45, blind-spot 44, verifier 23 runs; receipts approved 4, rejected 13, inconclusive 14 (phase1 §3); value unknown |
| 16 skills (`02-skills/*/SKILL.md`) | description always listed; body on invoke | 5,175 chars ≈ 1.3k tok always loaded | 0 | ≤ 3 invocations each after adoption (phase1 §8) [Measured] |
| `metodo` MCP server | on call | 31 tools, 14,438 B ≈ 3.6k tok if loaded up front; with tool search, names only | per call | 306 calls in 15 sessions (phase1 §8) |
| COM rules / `output_lint.py` | `human-reply` skill or the Stop hook | script: 0 tok; the rulebook loads only with the skill | ~60 ms | 14 rules active, 4 proposed (`07-communication/rules.md`) |
| comment gate | `necessary-comment` skill: script and a haiku agent | one small subagent | script plus one run | 15 runs (phase1 §3) |
| docs caps (`docs_lint.py`) | test suite, receipt finalize | 0 | 0.05 s real [Measured] | line caps; an offender rejects at finalize (`review-receipt.md` §4) |
| kit-status drift | `kit-status.sh --write/--check`, kit repo only | 0 | runs the full suite and `init.sh` twice (`kit_status.py` header) [Inferred: minutes] | README status never typed by hand |
| router (`router.py`) | before each launch (`mcp__metodo__route`) | prints the roster only | one script call | role/model/effort first-match table, offline post-pass (`router.py:35-38`, `:746`) |
| Engram (`memory.enabled: true`, `project.json:76`) | protocol injected each session; saves driven by reminders | protocol size not in this repo [Unknown], see `engram.md` | per call | recall median 0; 92% of sessions save nothing (phase1 §5) |
| pi extension (`hooks/pi/metodo-hooks.ts`) | runtime is pi | 0 | spawns the same `.py` files [Inferred: same latency] | same guards on pi; subagent output cannot be blocked |

Per main-session tool call: PreToolUse ~60-90 ms plus PostToolUse ~60-70 ms (parallel hooks on one event
cost the slowest). At 11.7 tool calls per human turn (phase1 §1): ~1.5-1.9 s per turn [Inferred].

## 2. Principles from the sources

1. **A warning that nobody acts on is a false positive.** Google defines an issue as an "effective false
   positive" when developers "did not take positive action after seeing the issue" [S11]. Clang turned
   cleaned-up diagnostics into errors, "(not a warning, which the Clang team found Google developers
   ignored)" [S11]. Kit reading: the kit's `warn` is not even seen (§1): a shadow log, useful for
   measuring, useless as feedback, so it needs an expiry after which it becomes BLOCK or OFF [Inferred].
2. **Blocking checks need no false positives; visible advisory checks need under 10%.** A compiler check
   must "produce no effective false positives (the analysis should never stop the build for correct
   code)". A review check must make developers feel it points at a real issue "at least 90% of the time".
   "If the ratio for an analyzer goes above 10%, the Tricorder team disables the analyzer until the
   author(s) improve it." [S11]
3. **Always-loaded context costs tokens on every turn; on-demand context costs only when used.** Each
   listed skill "adds to your context on every turn, whether or not Claude ever uses it" [S4]. With
   `disable-model-invocation`, a skill's "Description not in context, full skill loads when invoked"
   [S4]. "At startup, the agent pre-loads the name and description of every installed skill into its system
   prompt." [S8] "The budget scales at 1% of the model's context window." [S4] Subagents: "Those
   descriptions take up context, so keep them short." [S6] The guiding rule: "finding the smallest
   possible set of high-signal tokens that maximize the likelihood of some desired outcome" [S9].
4. **Defer tool definitions.** With MCP tool search, "Only tool names and server instructions load at
   session start" [S5]. Tool search "typically reduces this by over 85 percent" [S10]. CLI tools "are
   still more context-efficient than MCP servers because they don't add any per-tool listing" [S7].
5. **Scope hooks to where they matter.** "All matching hooks run in parallel." [S1] Subagent frontmatter
   hooks: "Claude Code runs them only while that subagent is running and removes them when it finishes"
   [S1]. They are skipped in untrusted folders, and "a `-p` session doesn't count as trusted" [S6].
   Absolute guards stay in settings. Since "the `if` filter is best-effort" [S1], use it to cut runs, never to
   enforce. "Claude Code uses the value from the highest level that sets it." [S2] Per-project switches
   (`skillOverrides`, hooks) go in `.claude/settings.local.json`, where `settings_merge.py` writes [Inferred].

## 3. Deterministic activation table

**Inputs.** None of them needs an LLM.

| Input | Values | Computed from |
|---|---|---|
| `rdd_on` | bool | `project.json` `rdd.enabled` (`_common.rdd_enabled`, `_common.py:80`) |
| `actor` | main / subagent | `agent_id` or `agent_type` on stdin (`_common.is_subagent`, `_common.py:89`) |
| `tier` | exempt / low / medium / high | `rdd_risk.derive` over touched paths, card and diff size; first match (`rdd_risk.py:69`) |
| `critical` | bool | a `shared_build_files` or `critical_paths` hit (the reasons `rdd_risk.derive` returns) |
| `kind` | research / docs / code / review / release / verify | the router's task descriptor `task_kind` |
| `phase` | explore / edit / deliver | no edit yet / `touched.jsonl` not empty / a Bash command matches `guard_gates.GATES` |
| `lang` | e.g. kotlin | `project.json` `language`, and whether `test_sectors.sectors` is empty |
| `runtime` | claude-code / pi | `CLAUDE_PROJECT_DIR` or the pi adapter's stdin |
| `offline` | bool | `router.resolve_offline`: task, then `project.json`, then `METODO_OFFLINE` (`router.py:324`) |
| `kit_repo` | bool | repo root holds `03-tools/lib/kit_status.py` and the README status markers |
| `tool_search` | bool | off if `ENABLE_TOOL_SEARCH=false`, a non-first-party `ANTHROPIC_BASE_URL`, or an older model [S5] |
| `verdict[e]` | keep / promote / demote | the §4 report, applied by the owner through a card |

**Profile rows.** First match wins; the profile is recomputed on each edit and never falls within a
session [Inferred].

| Row | Condition | Profile |
|---|---|---|
| P0 | `rdd_on = false` | bare |
| P1 | `tier = high` or `critical` or `kind = release` | full |
| P2 | `tier = medium` | standard |
| P3 | `tier = low` | scripts |
| P4 | `tier = exempt` (docs/research only, or still exploring) | light |
| P5 | tier not computable (no git, unreadable config) | standard (safe default, the same floor as `rdd_risk`'s no-card row) |

**Matrix.** ON = runs, visible. LOG = silent ledger line. WARN = visible, does not stop. BLOCK = deny, ask,
or send back once. The absolute set is BLOCK in every column, P0 included (`_common.py:4`,
`review-receipt.md` §5): force push without lease, subagent edits to build files or `.claude/`, subagent
delivery, the subagent call budget, `ask` on a main-session build-file edit.

| Element | bare | light | scripts | standard | full |
|---|---|---|---|---|---|
| push/PR/merge gate, no receipt (main) | OFF | OFF (an exempt receipt is born approved) | WARN | WARN, then per §4 | BLOCK (ask) |
| `--no-verify` / amend / rebase | OFF | LOG | LOG | LOG | LOG |
| subagent scope (`guard_paths`) | OFF | OFF | LOG | per §4 (now LOG) | BLOCK |
| subagent JSON output | OFF | OFF | BLOCK once | BLOCK once | BLOCK once |
| `touched_paths` | OFF | ON | ON | ON | ON |
| `session_start_status` | OFF | ON | ON | ON | ON |
| `reply_lint` Stop hook | OFF | OFF | OFF | OFF | OFF until §4 sampling; then BLOCK once on COM-01/COM-15 only |
| `human-reply` skill (lint, visible) | on demand | on demand | on demand | on demand | ON for status/decision replies |
| roles (cap; the router picks inside it) | none | none, inline | mechanic or proposer | adds challenger (1 lens) and verifier | adds blind-spot adversary, judge, boundary reviewer, cartographer if map is stale |
| comment gate | OFF | OFF | script | script, plus agent if `new_comments > 0` | script plus agent |
| docs caps | OFF | BLOCK at finalize | BLOCK | BLOCK | BLOCK |
| test sectors / verify | OFF | OFF | touched sectors | touched sectors | `full_required` |
| kit-status drift | BLOCK if `kit_repo` | same | same | same | same |
| router | when launching | when launching | ON | ON | ON |

**Session-start elements** (fixed per session, since settings load at start [Inferred]). `skillOverrides`:
`"user-invocable-only"` for owner workflows with side effects (`init-kit`, `post-review-comment`,
`benchmark-release`, `real-environment-minutes`, `verify-per-commit`, `clean-pass`), `"on"` for the rest.
`metodo` MCP ON (without `tool_search` the doctor reports its ~3.6k tok). Engram: reminders OFF, recall on
demand (`engram.md` owns this). pi extension ON exactly when `runtime = pi`.

**Modifiers**, applied after the profile:
- **M1.** A subagent skips main-only elements (reply lint, banner, owner gate), as the code already does;
  subagent-only elements (budget, scope, output) use the parent's profile.
- **M2.** `runtime = pi`: a BLOCK on subagent output becomes LOG (`invalid-unenforced`).
- **M3.** `offline`: the router's offline post-pass runs and `cite_check --online` is OFF.
- **M4.** `phase = explore`: nothing is touched, so `rdd_risk` returns `exempt` ("no touched paths") and
  the profile is light until the first edit. `phase = deliver`: the gate re-derives the tier against base.
- **M5.** `lang` with no Gradle build: test sectors OFF (the map is Gradle tasks). Gradle with empty
  `sectors` makes every path unmapped and `full_required` true (`project.json` `test_sectors._comment`).
- **M6.** An applied `verdict[e]`: demote means OFF, promote means BLOCK; never automatic.

## 4. Does an element earn its place? Measurement and rule

Data: `out/hooks/<session>/ledger.jsonl` (`_common.py:185-187`), `run-meta.json` (start date),
`false-positives.jsonl` (`hooks_report.py:140`), `out/rdd/*.receipt.json`. Per (hook, kind) per window:

- **Fires F**: ledger lines with decision `warn|deny|ask|block`. **Block rate**: `deny|ask|block` over F.
- **Opportunities O**: hook runs. Missing today, because silent passes are not logged. Fire rate is F/O.
- **Override rate**: an `ask` followed by `<kind>-outcome ran` on the same tree (the owner said yes),
  over the asks. Count it as a candidate false positive.
- **Act rate** (WARN or BLOCK-once only): the corrective event follows in the same session. Gate: a
  receipt `approved` for that tree before the next push. Scope: no later edit outside scope. Output: the
  next SubagentStop of the same `agent_id` passes. A LOG element has no act rate by construction.
- **Precision**: 1 − FP/k over k fires picked deterministically (the lowest `sha256(session:seq)`) for
  the owner to mark.

**Rule.** Thresholds in config (`rdd.activation.thresholds`); changing one or applying a verdict needs a
card (`methodology.md:196`). Window: `min_days` 7 (`hooks_report.py:152`) and `min_fires` 20 per element.

1. **Demote to OFF** when precision < 0.90, or the override rate is > 0.10 (Google's 10% [S11]), or a
   WARN element has an act rate < 0.10. Also when a non-absolute element has 0 fires in 2 windows and
   runs on every call.
2. **Promote to BLOCK** when the window is met, precision ≥ 0.90, there are ≤ `max_false_positives`
   (2, `hooks_report.py:154`) confirmed FPs, and 0 confirmed FPs for a main-session deny. Blocking checks
   need no false positives [S11]; an `ask` can carry the 2 because the owner decides.
3. **Expiry.** A LOG or WARN element lives at most 2 windows; then anything not promotable is demoted.
   "Keep warn" is not a valid verdict. The absolute set is exempt from 1-3 (owner decision only).
4. **Output.** `hooks_report` emits per-element verdicts with reasons. Today's flip criterion is one
   global test (days, receipts, FP count; `hooks_report.py:117`) with no act rate.

Applied to Phase 1 [Inferred]. `reply_lint` is past expiry (logging since 2026-09-15) and its mode is
ignored, since it always logs `warn` (`reply_lint.py:36`): hook OFF, skill kept; COM-01 and COM-15 (objective
shape rules) go to BLOCK once if sampling shows precision ≥ 0.90. `scope-outside` (50 LOG): sample k = 20,
then decide. `budget` is absolute: keep it, but measure findings per denied run (H3) before tuning caps.

## 5. How it plugs into existing code (design sketch) [Inferred]

- **`lib/activation.py`.** A pure `derive(inputs, config) -> {profile, reasons, elements}` shaped like
  `rdd_risk.derive` (first-match rows, recorded reasons, no git inside), plus `gather()`, a negative
  control and a determinism test (`methodology.md` §12). `touched_paths.py` caches the result in
  `out/hooks/<session>/profile.json` on each edit, so the other hooks make no git call on the hot path.
- **`_common.hook_mode(config, hook)`** (`_common.py:84`) becomes `hook_mode(config, hook, kind, profile)`.
  Resolution order: absolute → `rdd.activation.overrides[hook.kind]` → profile matrix →
  `rdd.hook_modes[hook]` → `rdd.mode` → `warn`. It gains the values `off` (return early, still count O)
  and `visible` (WARN through `additionalContext`/`systemMessage`).
- **`project.json` `rdd.activation`.** It holds `{thresholds, overrides}`. The matrix default lives in
  code, and the config only overrides it, as `DEFAULT_RDD` does in `rdd_risk.py:36`.
- **Hot path.** `budget` keeps its `""` matcher in settings (frontmatter would fail open under `-p` [S6]);
  a shell pre-check skipping Python when stdin has no `agent_id` saves ~50 ms per main call. `guard_gates`
  gains `if` filters (`Bash(git *)`, `Bash(gh *)`); unparseable commands still run the hook [S1].
- **Counters, report, router.** Per-hook invocation counters give O; `hooks_report` gains per-element
  verdicts and expiry; the router takes `profile` as a roster cap.
- **`init.sh`, `settings_merge.py`, `doctor.py`.** Init writes default `skillOverrides`; the doctor checks
  hooks and `skillOverrides` against the profile defaults and prints the always-loaded token estimate.
  On pi, `HOOK_MATRIX` stays a mirror (`test_pi_extension.py`); M2 is already in the code.

## 6. Sources

Read 2026-10-18, fetched with `curl -sL` into `$TMPDIR/c3act` (kept). The 20 verbatim quotes were checked
against the fetched text and this file by `$TMPDIR/c3act/quote_check.py`: 20 of 20 found.

| ID | URL | HTTP |
|---|---|---|
| S1 | https://code.claude.com/docs/en/hooks.md | 200 |
| S2 | https://code.claude.com/docs/en/settings.md | 200 |
| S4 | https://code.claude.com/docs/en/skills.md | 200 |
| S5 | https://code.claude.com/docs/en/mcp.md | 200 |
| S6 | https://code.claude.com/docs/en/sub-agents.md | 200 |
| S7 | https://code.claude.com/docs/en/costs.md | 200 |
| S8 | https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills | 200 |
| S9 | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | 200 |
| S10 | https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool.md | 200 |
| S11 | https://storage.googleapis.com/gweb-research2023-media/pubtools/4365.pdf (Sadowski, Aftandilian, Eagle, Miller et al., CACM 61(4), April 2018), linked from https://research.google/pubs/lessons-from-building-static-analysis-tools-at-google/ | 200, 200 |
| bg | not quoted: https://code.claude.com/docs/en/hooks-guide.md; https://research.google/pubs/tricorder-building-a-program-analysis-ecosystem/ (abstract); https://www.anthropic.com/engineering/advanced-tool-use | 200 each |
| failed | https://cacm.acm.org/research/lessons-from-building-static-analysis-tools-at-google/ (403); Tricorder PDF guess (404); Johnson et al. ICSE 2013 PDF (404) | 403, 404 |

**Uncertainties.** Latency comes from one machine; tokens are chars/4; Engram protocol size and pi tool
deferral are unknown; act rate needs new ledger events; no element has a false-positive mark yet, so
every FP rate is unmeasured; thresholds are borrowed from Google's practice, not calibrated on this kit.
