# Phase 2 protocol: controlled A/B/C with seeded defects

Pre-registered at the commit that adds this file. Hypotheses H1–H6 are frozen in `reports/phase1-findings.md`; a hypothesis Phase 2 does not confirm is reported as not confirmed. Nothing starts before the owner approves the cost forecast in §6.

Spec: `odd/tasks/methodology-benchmark.md` S2, S3, S7, S9, S10, S20, S21, S22.

## 1. Arms

| Arm | Environment | What differs |
|---|---|---|
| `vanilla` | `METODO_TOOLS=/nonexistent claude -p --disable-slash-commands --strict-mcp-config` | no kit hooks, skills or MCP |
| `kit` | `claude -p` with the kit installed | hooks, skills, agents, `metodo` MCP, Engram |
| `kit-no-engram` | as `kit`, with the Engram MCP server removed from the session (`--strict-mcp-config --mcp-config <kit-only.json>`) and the Engram hooks silenced | the ablation for H5 |
| `code-review` (comparator, added after the PR 176 pilot) | `vanilla` environment plus `prompts/arm-code-review.txt`, which invokes Claude Code's built-in `code-review` skill | the realistic alternative a team already has; the kit must beat this, not only vanilla |

Kit arm setup (`kit`, `kit-no-engram`): the repository is prepared with `03-tools/bin/init.sh <repo>` at the pinned sha, before any run. A kit run is accepted only if the init report `<instance>/out/init/<repo_sha>.json` for that repository sha has `ready_for_benchmark: true`, that is, the doctor's `kit_installed` and the smoke's `loop_ran` are both true; otherwise the run is `status: invalid-arm`. This adds to the transcript-evidence rule in §6, it does not replace it.

Constant across arms: model (`claude-opus-5-5`), `--effort high`, the task prompt, the tool allowlist, `--permission-prompts none`, the repository sha, session persistence on. The coordinator (this session, Fable 5.1) designs and aggregates; it never runs an arm and never judges.

## 2. Tasks

Base: project-a at one pinned sha on a throwaway branch per task, so the repository's own `CLAUDE.md`, standards and tests are the ones the kit claims to align with. Each task is a synthetic change with **seeded defects** whose file and line are recorded before any run (`tasks/<id>/seeded.json`, kept out of the arms' reach).

| Type | Count | Seeded defects per task | What it measures |
|---|---|---|---|
| T-review: review a PR branch | 4 | 3–5 (null-safety, off-by-one, missing idempotency key, missing test, logging in a hot path) | M25, M26, M22, M43 |
| T-fix: make a failing test pass | 3 | 1 real defect + 1 decoy that must not be "fixed" | M20, M23, M32 |
| T-feature: small feature with PR message | 2 | none seeded; standards conformance is the target | M42, M23, M24, M22 |
| T-resume: continue a feature started in a previous session | 1 | none; the previous session's context is the input | M53 (Engram ablation), M06 |

Total 10 tasks. Each task runs in every arm with 3 repetitions: 10 × 3 × 3 = **90 runs**. Run order is randomized per task; the arm label never appears in the prompt, the branch name or the working directory.

## 3. Judges

1. **Deterministic first.** Seeded-defect recall (`found / seeded`, by file and line), decoy touched yes/no, test suite pass/fail, `output_lint`/`comment_gate` verdicts, Conventional Commit regex, PR-template field presence, shape-metrics delta. Scripts in `08-benchmark/lib/`, each with a determinism test.
2. **Blind LLM judges, two, only for qualitative axes** (clarity, actionability, false findings): `claude-opus-5-5` and `claude-sonnet-5-5`, fresh sessions in an empty directory, no tools, A/B labels coin-flipped per pair, kit markers redacted as in `pr-review-ab.sh`. Agreement between judges is reported; disagreements are listed, not averaged away. Both judges are Anthropic models: self-preference bias is a stated limitation, mitigated by the deterministic layer carrying the headline metrics.

## 4. Metrics and labels

Every cell of the result table carries the METRICS.md id, its label and its status. Transcript-derived numbers (M01–M14, M60–M66) come from `transcript_metrics.py` over the 90 session ids; judge-derived numbers (M25, M26, M31) from the judge JSON; git-derived (M20–M24, M42) from `git_metrics.py` over each run's branch. A run whose arm fails (no output block, API error, denied allowlist) is `status: failed` and stays in the table.

Primary endpoints (one per hypothesis): H1 M04 parent peak context and M02 output tokens; H2 M25 seeded-defect recall and M26 false findings; H3 findings per denied vs completed subagent; H4 M43 reply conformance; H5 M53 resume cost in `kit` vs `kit-no-engram`; H6 M62/M33 cost per tier. Secondary: everything else in the catalogue.

Analysis: medians with bootstrap 95% intervals (stdlib `random` with a fixed seed, so the numbers reproduce); no p-values dressed up as proof. A difference whose interval crosses zero is "not shown".

## 5. Stopping and reporting rules

- Pilot first: the PR 176 cell (`pr-review-ab.md`) debugs the runner. Then one full task in all three arms × 1 repetition as a dry run; if any arm fails twice for protocol reasons, fix the protocol and restart the count.
- A task that fails in every arm (environment problem) is dropped and replaced; the replacement is recorded.
- The report lists every run, including failed ones, with its cost. Totals are reported before medians.

## 6. Cost and time forecast [vanilla: Measured on the PR 176 pilot; kit: Assumed until the rerun]

Measured on PR 176 (28 files, Opus 5.5 at `high`): vanilla review arm USD 1.3, ~100 s, 10 turns; kit arm running `receipt-review` (judge, confrontador and blind-spot adversary on opus-high, 23 `metodo` MCP calls) USD 8.4, 57 turns, 5.7M subagent tokens; Claude's built-in `code-review` skill USD 2.3; blind judge USD 0.6.

| Item | Runs | USD per run | Subtotal |
|---|---|---|---|
| `kit` + `kit-no-engram` arms | 60 | 6–10 (Measured on one PR: 8.4) | 360–600 |
| `vanilla` arm | 30 | 1–2 (Measured) | 30–60 |
| `code-review` comparator arm (added, see §1) | 30 | 2–3 (Measured) | 60–90 |
| Blind judges (2 per compared pair, ~60 pairs) | 120 | 0.6 (Measured) | 72 |
| Dry run and pilots | ~8 | as above | 30–60 |
| **Total** | | | **≈ USD 550–880** |

Wall-clock: vanilla ~2 min, kit arms ~10–15 min (Measured once: 57 turns); three in parallel gives roughly 5–8 hours of machine time.

Smaller variant if the budget is tighter: 6 tasks × 4 arms × 2 repetitions = 48 runs, ≈ USD 250–400, same hypotheses, wider intervals.

Pilot lesson written into the protocol: the kit arm's prompt must invoke the methodology (`prompts/arm-kit-review.txt`); a kit arm whose transcript shows no subagent, skill or `mcp__metodo__*` call is not a kit run and is marked `status: invalid-arm`.

## 7. What Phase 2 cannot answer

Long-horizon effects (weeks of delivery, team adoption), the router's value (no effort/model log exists in the kit; Phase 2 logs them from the transcripts instead), and anything about pi: the team runs Claude Code.
