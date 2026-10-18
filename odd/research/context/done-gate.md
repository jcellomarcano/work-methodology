# Done gate · a strict linter that flags before "done"

Research for S5 of `odd/tasks/context-optimization.md` (task C4). Read date 2026-10-18; kit lines cited at
`44bd74c`. External numbers are tagged **[Reported]** (the source says so; the kit did not re-measure them).
Sources and HTTP status in §6; every verbatim quote passed the script in §6.

## 1. Failure evidence: "done" without proof

**External [Reported].**

- Claude Code's own guidance names the mechanism: "Claude stops when the work looks done." (S2). Its fix
  is evidence, not trust: "Have Claude show evidence rather than asserting success" (S2).
- MAST, 1642 annotated multi-agent traces (S6): premature termination (FM-3.1) 6.20%, no or incomplete
  verification (FM-3.2) 8.20%, incorrect verification (FM-3.3) 9.10%. FM-3.1 is defined as "Ending a
  dialogue, interaction or task before all necessary information has been exchanged or objectives have
  been met". Verifiers that exist still fail: "many existing verifiers perform only superficial checks,
  despite being prompted to perform thorough verification, such as checking if the code compiles or if
  there are leftover TODO comments". Adding a high-level objective check gave +15.6% task success.
- Tests that pass do not prove the fix: on SWE-bench Verified, a weak validation "causes 7.8% of all
  patches to count as correct while failing the developer-written test suite", inflating resolution by
  6.2 points (S8). On SWE-bench, "31.08% of the passed patches are suspicious patches due to weak test
  cases"; filtering them dropped SWE-Agent+GPT-4 from 12.47% to 3.97% (S9).
- Agents game the check itself. METR saw frontier models "modifying the tests or scoring code"; reward
  hacking in 6/24, 12/28 and 21/21 runs of three tasks (S10). ImpossibleBench: "an LLM agent with access to
  unit tests may delete failing tests rather than fix the underlying bug" (S11).
- Self-checking does not replace an outside check: "LLMs struggle to self-correct their responses without
  external feedback, and at times, their performance even degrades after self-correction" (S12);
  "significant performance collapse with self-critique and significant performance gains with sound
  external verification" (S13).
- Human practice says the same: "If a Product Backlog item does not meet the Definition of Done, it cannot
  be released or even presented at the Sprint Review." (S4); and a reviewer asks "Will the tests actually
  fail when the code is broken?" (S5).

**Kit's own cases [Measured].**

- PR 176 pilot: the "kit" arm was reported as a kit run, yet "Its transcript has no subagent, no skill and
  no `mcp__metodo__*` call" (`08-benchmark/reports/pilot-pr176.md:28`). Only a manual transcript check
  caught it (`odd/tasks/methodology-benchmark.md:64`).
- Phase 1: kit hooks really ran in 42 of 85 sessions of one project and 0 elsewhere
  (`08-benchmark/reports/phase1-findings.md:12`): "installed" was claimed where it was not active.
- The final-reply lint never blocks (`03-tools/hooks/reply_lint.py:3`) and calls the linter with
  `kind=None` (`03-tools/hooks/reply_lint.py:33`), so COM-10 "Not tested" returns SKIP on every Stop
  (`03-tools/lib/output_lint.py:157-158`). The rule that should catch an unproven "done" is off at the one
  moment that matters.

No count exists for how often kit sessions said "done" without a green run [Unknown]; §5 says how to get it.

## 2. What the kit already checks, and what each piece misses

| Piece | Checks | Misses for "done" |
|---|---|---|
| methodology §0, §2, §10-§12 | law: evidence or silence; every commit green; "what was NOT tested" | a law, not a detector; nothing reads the reply against it at stop time |
| change card "How we'll know" (`00-principles/change-card.md:16`) | the field is filled | never checks that the named test or script ran |
| `rdd_receipt.py` finalize (`:430-503`) | captures, scripts, verifier, adversaries -> verdict | runs at review time, not reply time; `unreviewed` ack is born `approved` (`:549`), so "approved" alone does not mean reviewed |
| `kit_status.py --check` (`:365-386`) | README rows fingerprint, structure, docs caps (`:70`) | kit only; does not prove the suite ran or passed |
| `docs_lint.py` (`:31`) | listed docs under cap | iterates only `caps` keys: a new uncapped doc passes |
| `output_lint.py` COM-10 | `Not tested:` marker exists | needs `--type`; Stop passes none (§1); checks the marker, not that it lists the real skips |
| `cite_check.py` COM-19 | cited file:line exists; `[Measured]` without citation warns | existence, not content; a warn, not a block |
| `comment_gate.py` DOC-003 (`:70-73`) | unticketed TODO/FIXME, `NEEDS-COMMENT` | facts, not a verdict (`rdd_receipt.py:396-400`); only diff-added comments |
| `reply_lint.py` (Stop) | COM-01..18 FAILs to the ledger | never blocks |
| `validate_subagent_output.py` (SubagentStop) | JSON shape against the role schema; blocks once | shape only: `status: completed` with a failing command is valid JSON |
| `pr-message` checklist | DOC-003, kit-status, "What was NOT tested" | PR time only, followed by the model |
| `docs/02-workflow.md` exit criteria | "Every commit passes its own checks" | prose, no detector |
| `04-templates/feature-tasks.md:22` | "Check a box only after its outcome was observed" | honor system |

Gap [Inferred]: every piece checks one slice at its own moment; none sits between "the agent wrote
done" and "the person read done", and none ties the claim to a recorded green run on the current tree.

## 3. Done-gate design [Inferred]

One script, `lib/done_check.py`, reads files only (no model, no network, no test run inside the hook).
Input: repo, `HEAD^{tree}`, the session folder `out/hooks/<session>/` (ledger, `touched.jsonl`), a new
run log `runs.jsonl`, the final message, and `config/done-gate.json` (patterns, thresholds; changing it
needs a card). Output: JSON with ordered keys, `tool_sha`, `repo_sha`, `tree_sha`, `repo_dirty`, and
`rules[]` with `id`, `status` (`PASS` · `FLAG` · `BLOCK` · `SKIP` with reason), `evidence[]`, `fix`. Same
inputs, same output.

Why a run log: the Bash tool output a hook sees carries "`stdout`, `stderr`, `interrupted`, and
`isImage`" (S1), no exit code [Measured on the doc]. So the green proof is written by a thin wrapper,
`bin/run-check.sh <sector> -- <cmd>`, which appends `{seq, sector, cmd, exit, tree_sha}` to
`runs.jsonl`. A test run without the wrapper is "not recorded", never "green".

**Claim classes** (DONE-01 decides which apply): `done` (finished, listo, hecho, completed, fixed),
`green` (tests pass, all green, verde), `committed` (committed, commit `<sha>`), `delivered` (ready to
push, PR ready). No claim, gate silent.

| ID | Rule | Input | Check | Fail | Fix |
|---|---|---|---|---|---|
| DONE-01 | claim detection | final message | regex per claim class, outside code fences and quotes; also `status: completed` | none: selects rules | n/a |
| DONE-02 | green run for touched code | `touched.jsonl`, `runs.jsonl`, `test_sectors` | each touched non-exempt path's sector has a run with `exit 0` on the current `tree_sha`, `seq` after the last edit | BLOCK | run `bin/run-check.sh <sector> -- <cmd>` |
| DONE-03 | RED before GREEN | `runs.jsonl`, diff | a behavior change (src path touched, not refactor-only) has an earlier `exit != 0` run of the same sector whose tree held the new test | FLAG; BLOCK when strict TDD is on | rerun the test against the old code, or declare the exception |
| DONE-04 | no weakened test | diff of test paths | no deleted test function or assertion, no added skip/ignore/xfail marker | BLOCK | restore it, or owner waiver |
| DONE-05 | docs caps | `docs_lint.py`, touched `.md` | zero offenders; a new `.md` in a capped folder has a cap | BLOCK / FLAG | trim, or add the cap with a card |
| DONE-06 | README status block | `kit-status --check` | exit 0 when fingerprinted kit paths were touched (kit repo only) | BLOCK | `kit-status.sh --write`, commit README |
| DONE-07 | receipt | `out/rdd/<tree>.receipt.json` | for `delivered`: `approved` by review, or `owner_ack` recorded and quoted | BLOCK | run the receipt loop or ask the owner |
| DONE-08 | every spec judged | active `odd/tasks/*.md` | each `S#` sits in a row marked done with non-empty evidence, or carries a verdict | BLOCK for a feature claim | fill the row or say the spec is open |
| DONE-09 | card verification ran | change card `How we'll know` | each named test, script or command appears in `runs.jsonl` | FLAG | run it, or list it under Not tested |
| DONE-10 | "Not tested" present | final message, skips found by 02/03/09, `--no-verify` in the ledger | if any skip exists, a `Not tested:` / `No probado:` line names it | BLOCK | add the line with each skip |
| DONE-11 | no unticketed action tag | `comment_gate.py` on the diff | zero DOC-003 flags | BLOCK | `TODO(KEY-###):` or remove |
| DONE-12 | no `NEEDS-COMMENT` | touched files | zero markers | BLOCK | run the comment-gate round |
| DONE-13 | committed means committed | `git status --porcelain`, cited shas | for `committed`: touched paths clean; each cited sha reachable from HEAD | BLOCK | commit, or say "uncommitted" |
| DONE-14 | citations exist | `cite_check.py` on the message | zero MISSING | BLOCK | fix the path, line or sha |
| DONE-15 | tags have evidence | message, `runs.jsonl` | a `[Measured]`/`[Tested]` unit has a citation, a pasted output, or a run in this session | FLAG | cite, paste, or lower the tag |
| DONE-16 | subagent status matches validation | writer's return block | `status: completed` with any validation line not exit 0 and not named a known failure | BLOCK | `status: partial` |
| DONE-17 | nothing left running or lying around | Stop `background_tasks`, untracked files | no running shell task; no untracked `*.tmp`, `*.orig`, `*.rej`, `tmp/` | FLAG | stop it, delete, or say why it stays |

Layer scoping: an `exempt` receipt tier (docs only) skips 02, 03, 04, 09; a non-kit repo skips 06; a
reply with no claim skips everything. Each SKIP says why, so silence is never read as PASS.

## 4. Where it runs, the flag, the override

**Stop hook** (`hooks/done_gate.py`, main session). Reads the Stop input; `last_assistant_message` is
the claim. On BLOCK in `block` mode it exits 2 with the flag on stderr (or `{"decision": "block",
"reason": ...}` as `_common.emit_stop_block` already does, `03-tools/hooks/_common.py:211-212`). Exit 2 on
Stop "Prevents Claude from stopping, continues the conversation" (S1), and the reason becomes the next
instruction. Loop guard: Claude Code ends the turn after a cap, "after stop hooks have continued the turn
eight times in a row, Claude Code overrides the next block and ends the turn" (S1); the kit blocks once
per `tree_sha` + rule set (marker file, same pattern as `validate_subagent_output.py:70-76`), and with
`stop_hook_active` it lets the stop through and logs `done-unproven` to the ledger, which the next
`session_start_status` shows. Cost: file reads only, inside the 10 s hook timeout
(`03-tools/hooks/hooks.settings.json:22-24`). Starts in `warn` (ledger only) like every RDD hook.

**SubagentStop** for writer roles: DONE-16 plus 02/04/13 on the subagent's touched paths; the reason goes
back to the subagent as its next instruction (S1). **TaskCompleted**: same check before a task closes;
exit 2 "Prevents the task from being marked as completed" and the docs suggest exactly this use, "to
enforce completion criteria like passing tests or lint checks before a task can close" (S1).

**`bin/done-check.sh <repo> --claim done|green|committed|delivered [--reply file] [--session id]`** for
people and CI: same JSON; exit 0 PASS or FLAG only, 1 any BLOCK, 2 usage. Exposed as
`mcp__metodo__done_check`.

**Skill step**: `human-reply`, `pr-message` and the writer return contract call `done_check` before the
final reply and paste its flag block verbatim. A missing block when the ledger shows a FLAG is itself a
COM rule (proposed COM-20, detector in `output_lint.py`).

**Flag format** (the agent copies it as is, first lines of the human layer):

```text
DONE-GATE: BLOCK 2 · FLAG 1 · tree 1a2b3c4 · tool 9f8e7d6
- DONE-02 BLOCK no green run for sector 03-tools after the last edit (03-tools/lib/router.py) · fix: bin/run-check.sh 03-tools -- python3 -m unittest discover tests
- DONE-10 BLOCK DONE-02 is a skip and the reply has no "Not tested:" line
- DONE-15 FLAG [Tested] on line 14 has no citation, no pasted output, no run
```

**Owner override**: `done-check.sh --waive DONE-xx --reason "<text>"`, accepted only from the owner's
terminal: `guard_gates.py` treats an agent's `--waive` call as an owner gate (`ask`), the same way it
treats push. The waiver goes to `ledger.jsonl` with rule id, `tree_sha`, reason, and `git config
user.email`; it dies when the tree changes; the flag block then shows `WAIVED by <email>: <reason>` instead
of disappearing. No silent exception, the same rule `output_lint.py --allow` follows (`07-communication/rules.md:73-74`).

## 5. False-positive control and how to measure it

- **Negative and positive fixture per rule** (`tests/fixtures/done_gate/`): a session that must PASS and
  one that must BLOCK, plus a determinism test (same inputs, byte-identical JSON). Kit doctrine, §12.
- **Claim detector precision first.** DONE-01 decides everything downstream. Replay the stored Stop
  inputs (Phase 1 has 110 sessions, `phase1-findings.md:3`), hand-label 50 final messages claim/no-claim,
  report precision and recall. Target [Assumed]: precision ≥ 0.9 before any rule leaves `warn`.
- **Warn week, per-rule counters.** `hooks_report.py` counts per rule: fires, waivers, waivers with reason
  `false-positive`, and fires later confirmed (the claim was indeed wrong). A rule moves to `block` only
  with ≥ 20 fires and a false-positive share ≤ 10% [Assumed thresholds, owner decision]; above that, the
  rule stays FLAG and its pattern is fixed with a card.
- **Known FP sources** [Inferred]: refactor-only diffs hitting DONE-03 (exempt when the diff touches no
  test assertion and the card says `What it risks: none`); generated or vendored test files in DONE-04
  (`exempt_globs`); a quoted user sentence with "done" in DONE-01 (quotes are excluded); long suites run
  outside the wrapper (DONE-02 says "not recorded", the fix is the wrapper, not a waiver).
- **False negatives** are the real risk: the gate proves a run happened, not that the tests are good (S8,
  S9). DONE-04 and the verifier role cover part of it; the rest stays with review.

## 6. Sources

Fetched with `curl -sL` into `$TMPDIR/c4done` on 2026-10-18 (not deleted). Quote check: a Python script
(`quotecheck.py <repo>`) strips HTML tags and backticks, collapses whitespace, and searches each quote
verbatim in its source page or repo file: 20/20 found (17 external, 3 kit).

| ID | Source | URL | HTTP |
|---|---|---|---|
| S1 | Claude Code, Hooks reference | https://code.claude.com/docs/en/hooks.md | 200 |
| S2 | Claude Code, Best practices | https://code.claude.com/docs/en/best-practices.md | 200 |
| S3 | Claude Code, Hooks guide (read, not quoted) | https://code.claude.com/docs/en/hooks-guide.md | 200 |
| S4 | Scrum Guide 2020, Definition of Done | https://scrumguides.org/scrum-guide.html | 200 |
| S5 | Google eng-practices, What to look for | https://google.github.io/eng-practices/review/reviewer/looking-for.html | 200 |
| S6 | Cemri et al., Why Do Multi-Agent LLM Systems Fail? (MAST) | https://arxiv.org/abs/2503.13657 (full text https://arxiv.org/html/2503.13657) | 200 |
| S7 | SWE-bench Verified page (context only) | https://www.swebench.com/verified.html | 200 |
| S8 | Wang et al., Are "Solved Issues" in SWE-bench Really Solved Correctly? | https://arxiv.org/abs/2503.15223 | 200 |
| S9 | Aleithan et al., SWE-Bench+ | https://arxiv.org/abs/2410.06992 | 200 |
| S10 | METR, Recent frontier models are reward hacking | https://metr.org/blog/2025-06-05-recent-reward-hacking/ | 200 |
| S11 | ImpossibleBench | https://arxiv.org/abs/2510.20270 | 200 |
| S12 | Huang et al., LLMs Cannot Self-Correct Reasoning Yet | https://arxiv.org/abs/2310.01798 | 200 |
| S13 | Stechly et al., Self-Verification Limitations of LLMs | https://arxiv.org/abs/2402.08115 | 200 |
| - | OpenAI, Introducing SWE-bench Verified | https://openai.com/index/introducing-swe-bench-verified/ | 403, not used |

First authors (Cemri, Wang, Aleithan, Zhong, Huang, Stechly) are from each page's `citation_author` tag
[Measured]. Not verified: METR's per-task counts against its full transcripts; MAST's percentages come
from the LLM-annotated set, not the human-annotated one [Reported].
