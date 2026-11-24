# Skill evals: the first runs at three per arm

Date 2026-11-24. Branch `fix/skill-evals-arm-tools`, feature `odd/tasks/skill-evals.md` (S14 to S16). Four
invocations of `08-benchmark/lib/skill_eval.py run --skill <name> --real --runs 3 --model haiku --judge-model haiku --max-cost-usd 0.25`,
USD 0.141 in all, on runner version 5. `change-card` ran with `--kit-mcp`. The files beside this one are the
runner's own output with machine paths replaced by `<home>` and `<tmp-path>`. No report was published.

| File stem | Skill, and what the case was | USD | Verdict | With the skill | Without it |
|---|---|---|---|---|---|
| `run1-change-card-strict-expectation` | `change-card`, as first written | 0.036 | `review`: the judge rejects it | triggered 3 of 3; validator 3 of 3; judge 1 of 3 | validator failed 3 of 3 |
| `run2-change-card-reworded-expectation` | `change-card`, first expectation reworded | 0.037 | `works`: with 1.00, without 0.00 | triggered 3 of 3; validator and judge 3 of 3 | validator failed 3 of 3 |
| `run3-post-review-comment` | `post-review-comment` | 0.035 | `review` [signal: 2 of 3 runs per arm scored]: it does not trigger when it should | triggered 1 of 3; that one passed | validator failed 2, one timed out after 240 s |
| `run4-change-card-corrected-validator` | `change-card`, as it ships (validator corrected after the verifier) | 0.033 | `review` [signal: 1 of 3 runs per arm scored]: the judge rejects it | triggered 3 of 3; validator 3 of 3; judge 2 of 3 | 2 ran out of their 10 turns, 1 failed the validator |

## What these runs prove [Tested, three runs per arm, one model]

- With the server kept in both arms, the arm without the skill reached the same tools under the same names:
  7, 8 and 8 calls to `mcp__plugin_change-card_metodo__*` in the runs without the skill. The real tool runs a
  plugin that holds a server and no skill.
- On the rewritten case `change-card` triggers, nine times of nine.
- The skill is what makes the difference the script can see: with it, nine runs of nine left "What it risks"
  to the author and passed the validator; without it none of nine passed, seven because they wrote that field
  and two because they ran out of turns.

## The verdict is not steady yet, and why

`run2` reads `works` and `run4` reads `review` on the same expectations. In `run4` one answer said the card
"still fails validation and can't go to a proposer yet", named the `opus` routing and sent it to the owner;
the judge's three votes on the third expectation were no, yes, no. At three runs per arm the limit of 0.8
needs three passes of three, so one split vote of a `haiku` judge flips the verdict. More runs per arm or a
stronger judge model would settle it; both are a spend decision of the owner.

## What changed between the runs, and why it is said here

- Between `run1` and `run2`: the first expectation asked for the reason in its own words ("because only the
  owner, as its author, writes it"). Two answers that left the field out and said so ("I didn't write it, and
  I left it out of the file. It needs your judgment") were rejected by all three votes. It now asks for the
  substance. This was changed after seeing a result, so both runs are kept.
- Between `run2` and `run4`: the validator's rule against an empty draft took a fixed word list; the
  independent verifier showed it failed faithful drafts, and it now draws its words from the staged card.
  No expectation changed. No run of the nine was failed by that rule, before or after.

## What they do not prove

- That `change-card` works on any other prompt, card or model: one case, one model.
- Why `post-review-comment` triggered once in three. In the two runs that did not invoke it the model went
  straight to the shell, as `change-card` went straight to its tool before its case was rewritten; the same
  look at the case is the next step. Its arm without the skill is the tool's own ablation, since the skill
  declares no server tool.

## The same two skills at five runs per arm

One more invocation for both skills with `--runs 5`, USD 0.118, files `run5-both-skills-five-runs.*`. The day's
five invocations cost USD 0.258.

| Skill | Verdict | With the skill | Without it |
|---|---|---|---|
| `change-card` | `works`: with 0.80, without 0.00 | triggered 5 of 5; validator 5 of 5; judge 4 of 5 (one answer rejected on the second expectation) | none of 5 passed: 3 wrote "What it risks", 1 left the draft out, 1 passed the validator and was rejected by the judge |
| `post-review-comment` | `review`: it does not trigger when it should | 0 of 3 scored runs invoked it; 2 timed out after 240 s | validator failed 5 of 5 |

At five runs the limit of 0.8 is met by four passes of five, so one rejected answer no longer flips
`change-card`. `post-review-comment` got worse, not better, with more runs: no scored run invoked the skill.

## All 17 skills at five runs per arm

Branch `feat/skill-evals-all-skills` (S17): the 15 skills that had no case got one, and every skill with a case
was run with `--kit-mcp --real --runs 5`, `haiku` for model and judge, ceiling USD 0.25 per skill. Files
`run6-all-skills-group1..4.*` (four runner processes side by side) and `run7-<skill>-corrected-validator.*`: three
cases ran again after the independent verifier found their validators failing faithful outputs, and the row
below is their second run. USD 1.421 in all for these runs; the writers' own proof runs of the new cases, one
run per arm, cost USD 0.369 more. With the runs above, the day's real runs cost USD 2.05.

| Skill | Verdict | With | Without | Triggered | Runs with the skill | Runs without it | Note |
|---|---|---|---|---|---|---|---|
| `adversarial-round` | `review` | n/a | 0.00 | 0 of 5 | 0 passed, 0 failed the validator, 0 rejected by the judge, 5 not triggered | 0 passed | |
| `benchmark-release` | `review` | 1.00 | 1.00 | 5 of 5 | 5 passed, 0 failed the validator, 0 rejected by the judge, 0 not triggered | 5 passed | |
| `cartography` | `review` | 0.40 | 0.00 | 5 of 5 | 2 passed, 3 failed the validator, 0 rejected by the judge, 0 not triggered | 0 passed | |
| `change-card` | `works` | 0.80 | 0.00 | 5 of 5 | 4 passed, 0 failed the validator, 1 rejected by the judge, 0 not triggered | 0 passed | stored result |
| `clean-pass` | `works` | 0.80 | 0.00 | 5 of 5 | 4 passed, 1 failed the validator, 0 rejected by the judge, 0 not triggered | 0 passed | |
| `harness-benchmark` | `review` | 0.00 | 0.00 | 5 of 5 | 0 passed, 5 failed the validator, 0 rejected by the judge, 0 not triggered | 0 passed | |
| `human-reply` | `review` | 0.40 | 0.00 | 5 of 5 | 2 passed, 1 failed the validator, 2 rejected by the judge, 0 not triggered | 0 passed | |
| `human-review` | `works` | 0.80 | 0.00 | 5 of 5 | 4 passed, 0 failed the validator, 1 rejected by the judge, 0 not triggered | 0 passed | |
| `init-kit` | `review` | 0.60 | 0.00 | 5 of 5 | 3 passed, 0 failed the validator, 2 rejected by the judge, 0 not triggered | 0 passed | |
| `necessary-comment` | `review` | n/a | 0.00 | 0 of 5 | 0 passed, 0 failed the validator, 0 rejected by the judge, 5 not triggered | 0 passed | |
| `post-review-comment` | `review` | 0.00 | 0.00 | 3 of 5 | 0 passed, 3 failed the validator, 0 rejected by the judge, 2 not triggered | 0 passed | |
| `pr-message` | `works` | 1.00 | 0.00 | 5 of 5 | 5 passed, 0 failed the validator, 0 rejected by the judge, 0 not triggered | 0 passed | |
| `real-environment-minutes` | `works` | 0.80 | 0.20 | 5 of 5 | 4 passed, 0 failed the validator, 1 rejected by the judge, 0 not triggered | 1 passed | |
| `receipt-review` | `review` | 1.00 | 0.00 | 1 of 5 | 1 passed, 0 failed the validator, 0 rejected by the judge, 4 not triggered | 0 passed | |
| `repo-metrics` | `works` | 0.80 | 0.40 | 5 of 5 | 4 passed, 0 failed the validator, 1 rejected by the judge, 0 not triggered | 2 passed | |
| `review-comment` | `works` | 1.00 | 0.00 | 5 of 5 | 5 passed, 0 failed the validator, 0 rejected by the judge, 0 not triggered | 0 passed | |
| `verify-per-commit` | `review` | 0.80 | 1.00 | 5 of 5 | 4 passed, 0 failed the validator, 1 rejected by the judge, 0 not triggered | 5 passed | |

Seven read `works` and ten read `review`. The ten are not one finding [Tested, five runs per arm, one model,
one case per skill]:

- **Three do not trigger** (`adversarial-round`, `necessary-comment`, `receipt-review` once in five). Their
  cases start after the step their descriptions name, because a run cannot launch role agents and its folder is
  no git repository; the prompt then reads as a question about files.
- **Five trigger and do not pass.** `harness-benchmark`: every summary rounded or recomputed numbers, which the
  skill forbids. `init-kit`: two answers showed the command without the runtime option. `cartography`: two maps
  left a measured module's LOC out and one run saved no file. `human-reply`: the judge rejected two answers and
  one reply lost a tag. `post-review-comment`: the three runs that invoked it left no `posted.md`.
- **Two do no better than without the skill.** `benchmark-release` passed in both arms every time;
  `verify-per-commit` passed five of five without the skill and four of five with it, one answer rejected by
  the judge.

What the runs without the skill show: with the kit's tools at hand and a clear input, `haiku` often reaches the
right decision unaided. Where a skill reads `works`, the difference is mostly the output its text prescribes
(the sections of a PR message, the four parts of a review comment, the fields of a brief), and in `change-card`
and `clean-pass` a rule about what not to write.

## Mocked tools answer in both arms (run 8, the proof of the mechanism)

Two real runs on a temp copy of `repo-metrics/smoke-tool-drift`, one run per arm, `haiku` for model and judge,
ceiling USD 0.10 each, USD 0.0232 in all [Measured]. The copy differs from the kit's case in three ways:
`mocks/metodo/job_status.md` was added (its body is the case's own `setup/job-status.json`, byte for byte),
that file is no longer staged, and one sentence of the prompt asks the job for its status instead of pointing
at the file. The mock and the prompt are kept beside this page as `run8-mocks-proof.job_status.mock.md` and
`run8-mocks-proof.prompt.md`.

| run | tool list file | verdict line | mocked tool calls, with / without | file |
|---|---|---|---|---|
| 1 | none | `review`: with rejected by the judge, without failed a validator | 1 / 1 | `run8-mocks-proof-no-tool-list.stdout.txt` |
| 2 | generated from the kit's server | `works`: with 1.00, without 0.00 | 1 / 1 | `run8-mocks-proof-with-tool-list.stdout.txt` |

What it proves [Measured, Claude Code 2.1.330]: a hand-written mock under `mocks/<server>/<tool>.md` is answered
for a server the plugin declares, with the real server not started; the arm without the skill, run as a second
invocation on the plugin less the skill's folder, keeps the mocked tool and called it; without the tool list
file each run carries a warning that the tool was served with a permissive schema and no description, and with
the file in the shape `{"tools": [...]}` the warning is gone. What it does not prove: one run per arm is no
verdict; the difference between the two runs cannot be put on the tool list file alone; a declared tool with
no mock (`metrics_delta` here) is not available to the model, so a case must mock every tool its scenario
needs.

## Ten cases with mocks, one run per arm (run 9, the writers' proof runs)

Each row is the last proof run a writer made of a case after it gained its mocks: one run per arm, `haiku` for
model and judge, ceiling USD 0.10, through `08-benchmark/bin/skill-eval.sh run <skill> --real`. One run per arm
is a signal, never a verdict [Measured]. Spend: USD 0.1749 over 15 runs (0.0678 + 0.0454 + 0.0458 + 0.0159).

| skill | tools mocked | with the skill | without it | mocked calls, with / without |
|---|---|---|---|---|
| `cartography` | `cartography` | passed | failed a validator | 1 / 1 |
| `repo-metrics` | `metrics_delta`, `job_status` | passed | passed | 2 / 2 |
| `clean-pass` | `clean_pass` | passed | failed a validator | 1 / 1 |
| `benchmark-release` | `benchmark_release`, `job_status` | passed | passed | 2 / 2 |
| `verify-per-commit` | `verify_commit`, `job_status` | passed | passed | 2 / 2 |
| `real-environment-minutes` | `benchmark_release`, `job_status`, `domain_invariants`, `change_card_extract` | passed | passed | 4 / 2 |
| `review-comment` | `pr_scope` | passed | failed a validator | 1 / 1 |
| `pr-message` | `change_card_validate`, `receipt_status` | rejected by the judge on one expectation | failed a validator | 2 / 0 |
| `receipt-review` | `receipt_status`, `test_sectors` | not triggered | failed a validator | 0 / 1 |
| `necessary-comment` | `comment_gate_measure` | passed | failed a validator | 1 / 1 |

Earlier proof runs of the same cases, each followed by a change to the case: `cartography` and `repo-metrics`
first saved the output under `out/<sha>/` because the prompt said the tool's files land under `out/` (prompt
reworded); `receipt-review` first carried a mock of `receipt_start`, which the run with the skill declined to
call on an open receipt, so the lenses were out of reach (mock dropped, the receipt staged where the tool
writes it). The stdout of the runs of the first six rows is kept as `run9-mocks-<skill>-<n>.stdout.txt`; the
last four rows are as their writers reported them (the feature document, L37).

What the rows show [Inferred, one run per arm]: `necessary-comment` never triggered in five runs when its case
began after the measure, and triggered and passed when the case asks for the gate itself. In four cases
(`repo-metrics`, `benchmark-release`, `verify-per-commit`, `real-environment-minutes`) the run without the
skill passed too once the tools answered; the last of these read `works` at five runs before, so it needs
five runs again before anything is concluded.

How the mock bodies were made: each is the answer of the kit's real server (`03-tools/mcp/server.py`, one
`tools/call` over stdio, `METODO_REPO` on a scratch git repository rebuilt from the case's data). Where the
scratch repository could not reproduce the scenario's identities, the answer was relabeled and nothing else:
scratch paths to workspace-relative ones, scratch commit shas to the scenario's, the scratch kit sha to the
staged one. The scripts are under `mock-builders/`, one folder per writer; they name the kit checkout as
`KIT_ROOT`, to be replaced with its path before a run.

Seven skills carry no mock: `change-card` and `human-reply` (the tool is called again after the run rewrites
the file it checks, and answers differently), `adversarial-round` (one tool answers `PASS` for one document and
`INCOMPLETE` for the other, and the case stands on that difference), `harness-benchmark` (its first step is a
script of its own run through the shell; its two kit tools start a job with a fresh id), and `human-review`,
`init-kit`, `post-review-comment` (their text calls no kit tool).
