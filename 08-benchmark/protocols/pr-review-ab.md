# PR review A/B: one PR, two arms, one blind judge

A Phase 2 pilot cell. The same PR is reviewed twice with the same model, the same effort and the same prompt; the only difference is whether the kit is active. A third, blind session judges both reviews. You keep the better one and the benchmark keeps the numbers.

Spec: `odd/tasks/methodology-benchmark.md` S7, S20, S21.

## One command

```bash
08-benchmark/bin/pr-review-ab.sh <repo> <pr-id> <head-ref> <model> [effort]
```

Example: `08-benchmark/bin/pr-review-ab.sh ~/project-a 283 feature/dev-283 claude-opus-5-5 high`.

The script pins the PR head sha, computes the merge base with the default branch, saves the diff, runs both arms in a coin-flipped order, runs the blind judge with coin-flipped labels, and prints a summary. Outputs under `08-benchmark/data/ab/<pr-id>/` (local only):

| File | Content |
|---|---|
| `diff.patch` | `git diff <base>...<sha>` reviewed by both arms |
| `<arm>.raw.json` | the full `claude -p --output-format json` result: `session_id`, cost, durations, usage |
| `<arm>.review.json` | the findings array extracted from the reply |
| `<arm>.summary.json` | cost, tokens, turns, findings count, verdict |
| `judge.mapping.json` | which letter was which arm, and the run order |
| `judge.json` | the judge's validity counts and preference |
| `../ab-runs.jsonl` | one line per arm run, for `lib/transcript_metrics.py` |

## Arms

| Arm | Process | What makes it that arm |
|---|---|---|
| `kit` | `claude -p` in the repo | Hooks, skills, agents and the `metodo` MCP server as installed. The model decides whether to use them; the prompt does not mention them. |
| `vanilla` | `METODO_TOOLS=/nonexistent claude -p --disable-slash-commands --strict-mcp-config` in the same repo | Every kit hook exits silently (`[ -f "$H/..." ] \|\| exit 0`), no skills, no MCP servers. Residual: `.claude/agents/generic-*.md` stay discoverable by the `Agent` tool; the prompt never asks for them, and the transcript shows whether they were used (`agent_tool_calls_by_type`). |
| judge | `claude -p` in an empty temporary directory, same switches as `vanilla`, no tools | Reads the diff and the two reviews labelled A/B by a coin flip. Never sees arm names. |

Kit arm setup: the repository is prepared with `03-tools/bin/init.sh <repo>`; the kit arm counts only if that repository sha's init report (`<instance>/out/init/<repo_sha>.json`) has `ready_for_benchmark: true` (doctor `kit_installed` and smoke `loop_ran`), otherwise it is `invalid-arm`, on top of the evidence gate below.

Both arms get the same model, the same `--effort`, the same tool allowlist, `--permission-prompts none` (nothing waits for a human) and session persistence on, so `lib/transcript_metrics.py` can measure tokens, peak context, latency, subagents and compactions from the transcript.

Symmetric residuals (present in both arms, so they do not separate the arms): the repository's `CLAUDE.md`, and the user-level hooks in `~/.claude/settings.json` (gentle-ai review stop-hook and telemetry). `--bare` would drop those too, but it would also change the kit arm, so it is not used.

Blinding safeguards: a finding's `evidence` could quote a kit tool name or hook output; the copy the judge receives (`<arm>.review.blind.json`) has `mcp__*` names and kit/hook markers replaced by `[tool]` / `[redacted]`, the stored review stays intact. An arm whose reply has no findings block or returns an API error is marked `status: failed` and the judge is not run (exit 3): a failed cell is reported as failed, never scored (S9).

## Prompts

- Arm prompt: `protocols/prompts/arm.txt` (`<PR>`, `<SHA>`, `<BASE>` are substituted). Fixed findings JSON: id, file, line, severity, category, claim, evidence, fix, epistemic label; then `VERDICT: approve|request-changes`.
- **Kit arm prompt (required since the PR 176 pilot).** In `claude -p` a neutral prompt never starts the kit's review workflow, so the kit arm must be told to run it: `AB_ARM_PROMPT=protocols/prompts/arm-kit-review.txt` invokes `receipt-review`; `<CONTRACT>` in the template is replaced by `arm.txt`, so both arms deliver the same JSON shape and the judge stays blind. The vanilla arm always gets `arm.txt`. The `prompt` field in `data/ab-runs.jsonl` records which template each run used; a run whose kit arm used `arm.txt` is not a kit run.
- Comparators, not the kit: `arm-code-review.txt` (Claude Code's built-in `code-review` skill) and `arm-engineering-code-review.txt` (the `engineering:code-review` plugin). Runs with them answer "does Claude's own review skill beat vanilla?", and must be reported under that name, never as the kit. Give them their own output dir (`AB_OUT_DIR`) and their own evidence pattern (`AB_ARM_EVIDENCE='"skill":"code-review"'`), otherwise the kit-evidence gate stops them with exit 5.
- Evidence gate: after the non-vanilla arm, the runner greps its transcript for the evidence pattern (kit by default) and writes `kit_evidence_hits` into the arm summary; zero hits means `invalid-arm`, exit 5, no judge. A transcript that cannot be found is reported as unverified, not as valid.
- `AB_REUSE_VANILLA=<previous run dir>` copies that run's vanilla arm instead of re-running it; the runner refuses a baseline whose `diff.patch` differs.
- Judge prompt: `protocols/prompts/judge.txt` (`<DIFF>`, `<REVIEW_A>`, `<REVIEW_B>` are substituted). Per finding: valid / invalid / unverifiable; defects missed by both; clearer; preferred. "Do not reward length" is written into it.

## Reading the result

The script prints, per arm: findings, verdict, cost, turns, output tokens, cache reads, and the judge's valid / invalid / unverifiable counts mapped back to the arm, then `preferred: kit|vanilla`. Keep the preferred review for the real PR. For the benchmark, run `python3 lib/transcript_metrics.py --project <repo-dir> --out data/ab/<pr-id>/sessions.json` and filter by the two session ids in `ab-runs.jsonl`.

## What this pilot can and cannot say

It is one PR, one repetition, one judge: enough to debug the protocol and to pick the better review today, not enough to claim the kit is better. Phase 2 repeats this over N PRs with seeded defects and two judges, with the run order and labels randomized the same way.

## Interactive fallback

If `claude -p` is not an option, open two fresh interactive sessions (`claude --model <model>` and `METODO_TOOLS=/nonexistent claude --model <model>`), paste `prompts/arm.txt` with the placeholders filled, keep the same effort, and record the session ids by hand in `data/ab-runs.jsonl`. pi is not covered yet: the team runs Claude Code.
