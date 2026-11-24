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
