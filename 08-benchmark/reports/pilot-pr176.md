# Pilot cell: PR 176 (a contact-form feature) (project-a), 2026-10-13

One PR, two arms, one blind judge, run by the owner from a plain terminal with `bin/pr-review-ab.sh`; then a rerun with the kit actually invoked and two comparators (§4). Purpose: debug the protocol. Verdict on the kit: a signal, not a conclusion (§5).

Inputs: `feature/<redacted>` @ `<head-sha>` → `develop` (merge base `<base-sha>`), 28 files, +1,132/−7, no test files. Model `claude-opus-5-5`, effort `high`, identical prompt (`prompts/arm.txt`), run order kit → vanilla, judge labels A=kit, B=vanilla (coin flips recorded in `data/ab/176/judge.mapping.json`).

## 1. Numbers [Measured, from `data/ab/176/*.summary.json` and the two transcripts]

| | kit | vanilla |
|---|---|---|
| Findings | 7 | 6 |
| Judge: valid / invalid / unverifiable | 6 / 0 / 1 | 6 / 0 / 0 |
| Verdict | request-changes | request-changes |
| Cost (USD) | 1.28 | 1.34 |
| API turns | 9 | 10 |
| Wall-clock (s) | 104 | 102 |
| Output tokens | 10,474 | 10,253 |
| Cache read tokens | 682k | 806k |
| Peak context (one request) | 128,893 | 121,501 |
| Subagents / skills / MCP calls | 0 / 0 / 0 | 0 / 0 / 0 |
| Tool calls | Bash ×8 | Bash ×8, Read ×1 |
| Kit hook output seen | yes (session start, 2 runs) | no |

Judge: preferred B (vanilla), clearer B; reason: A's F2 (missing translation fallback) depends on remote translations outside the diff. Judge cost USD 0.63, 1 turn. Three defects missed by both arms, all in `ContactFormFragment.kt` (lifecycle scope at line 284, constructor argument at line 40, blocking configuration call at line 113), listed in `data/ab/176/judge.json`.

## 2. What the pilot proved about the protocol

1. **The kit arm did not run the kit.** Its transcript has no subagent, no skill and no `mcp__metodo__*` call; the only difference from vanilla was the session-start hook printing its status. In `claude -p` with a neutral prompt, the kit's review workflow does not start on its own. The two arms were the same experiment twice, and they behaved the same: same defects found, same verdict, cost within 5%. [Measured]
2. **A marker was contaminated.** `transcript_metrics.py` counted a kit hook run whenever the hook *command* contained `metodo`, including hooks that exited silently under `METODO_TOOLS=/nonexistent`. Fixed to require `[metodo]` in the hook's output; Phase 1 hook-run counts were recomputed (project-a 42 of 85 sessions; 0 in the other repos). [Measured]
3. **Cost forecast was 4–10× too high.** A full-PR review arm cost USD 1.3, not 5–15. The Phase 2 forecast is revised from this number. [Measured]
4. The runner, the redaction, the fail-closed paths and the tree check all worked as tested; the owner ran it without intervention. [Measured]

## 3. What it does not say

Nothing about the kit. With both arms effectively vanilla, "judge preferred vanilla" is a coin flip on one unverifiable finding. The cell is kept in the ledger as `prompt: arm.txt` and will be compared with a rerun whose kit arm invokes the methodology (`prompts/arm-kit-review.txt`, `AB_ARM_PROMPT`), reusing this vanilla arm as the baseline (`AB_REUSE_VANILLA`, same diff enforced).

## 4. Cell 176b and the comparators (same vanilla baseline, same diff, same judge setup)

Run by the owner after §3. The vanilla arm is the one from 176 (byte-identical review file, enforced by the runner's diff check). [Measured, from `data/ab/176b`, `data/ab-code-review/176`, `data/ab-engineering-code-review/176` and the transcripts]

| Arm (prompt) | Ran what it was asked | Findings | Judge valid / invalid / unverifiable | Cost USD | Turns | Peak context | Subagent tokens | Judge preferred |
|---|---|---|---|---|---|---|---|---|
| vanilla (`arm.txt`) | — | 6 | 6 / 0 / 0 | 1.34 | 10 | 122k | 0 | baseline |
| kit, neutral prompt (`arm.txt`, cell 176) | no: hooks only | 7 | 6 / 0 / 1 | 1.28 | 9 | 129k | 0 | vanilla |
| kit, `arm-kit-review.txt` (cell 176b) | yes: `receipt-review`, judge + confrontador + blind-spot adversary (opus-high), 23 `metodo` MCP calls, 4 Engram calls | 10 | 7 / 0 / 3 | 8.38 | 57 | 186k | 5.7M | **kit** |
| Claude `code-review` skill (`arm-code-review.txt`) | yes: skill + 1 general-purpose subagent | 10 | 8 / 0 / 2 | 2.25 | 11 | 117k | 1.2M | **code-review** |
| `engineering:code-review` plugin | skill invoked, no subagent | 7 | not judged (evidence gate, exit 5) | 1.22 | 11 | 121k | 0 | — |

Judge reasons: for 176b, "A has nothing invalid and covers everything B found plus more confirmed findings" (the duplicated underline setting; device rows that cannot all be hidden through `contactUsAvailableInfo` unless WhatsApp is on); the 3 unverifiable findings were called plausible leads, not false claims. For `code-review`: "A finds every real defect B finds plus more" (the telemetry flow collected in the fragment's scope, among others). Defects missed by both: 3 in 176b, 2 in the `code-review` cell.

## 5. Reading, with the n=1 caveat in front

- **The kit's review does find more confirmed defects than vanilla** on this PR (7 valid vs 6, plus 3 leads) with zero invalid findings. [Measured]
- **It costs 6.3× vanilla** (USD 8.38 vs 1.34) and 57 turns, because the methodology spawns three opus-high agents and makes 23 MCP calls. [Measured]
- **Claude's built-in `code-review` skill found one more valid defect (8) at about a quarter of the kit's price (USD 2.25).** On this PR it is the best value of the four. [Measured]
- The `engineering:code-review` plugin was not judged: the evidence gate was written for the kit and stopped it; the runner now takes `AB_ARM_EVIDENCE` for comparators. [Measured]

What this changes in the benchmark: the kit's real competitor is not vanilla but the review tooling a team already has. Phase 2 adds `code-review` as a fourth arm, and H2 is tested against it. What it does not change: one PR, one judge of the same model family, three unverifiable findings on the kit side that may or may not be real. A signal, not a conclusion.
