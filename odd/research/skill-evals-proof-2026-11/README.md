# Skill evals: the real runs

Date 2026-11-24. Branch `feat/skill-evals`, feature `odd/tasks/skill-evals.md`. Eight invocations of
`08-benchmark/lib/skill_eval.py run --real --runs 1 --model haiku --judge-model haiku --max-cost-usd 0.25`,
USD 0.072 in all. One run per arm, so every verdict here is a signal, not a result: three runs per arm is the
floor for a verdict (S7), and that run is the owner's spend decision (S11). The files beside this one are the
runner's own output with machine paths replaced by `<tmp>`, `<home>` and `<tmp-path>`. No report was published.

## Final runs, on the runner as it ships (runner version 3)

| File stem | Skill and flags | USD | Verdict | What the run did |
|---|---|---|---|---|
| `final1-post-review-comment` | `post-review-comment` | 0.012 | `review`: the judge rejects it | The skill was invoked and the saved file passed the script validator; the judge rejected one expectation about the answer. |
| `final2-change-card-kit-mcp` | `change-card --kit-mcp` | 0.007 | `review`: it does not trigger when it should | The model called `mcp__plugin_change-card_metodo__change_card_validate` directly and never invoked the skill. |
| `final3-change-card-kit-plugin` | `change-card --kit-plugin` | 0.008 | `review`: it does not trigger when it should | Loaded from the kit plugin alone, the plugin's own server answered `mcp__plugin_metodo_metodo__change_card_validate`; the skill was not invoked. |

## Earlier runs, made while the runner was being built (runner version 2)

| File stem | Skill and flags | USD | Verdict | What the run showed |
|---|---|---|---|---|
| `run1` | `post-review-comment` | 0.011 | `review`: its output fails a validator | The saved file lacked the bold labels the skill's script renders. The native tool alone scored this run 1.0. |
| `run2` | `change-card --kit-mcp` | 0.007 | `review`: it does not trigger when it should | Same as `final2`. |
| `run3` | `post-review-comment --no-cache` | 0.013 | `not measured` | The run with the skill timed out after 240 s; cause unknown. |
| `run4` | `change-card --kit-plugin` | 0.007 | `review`: it does not trigger when it should | Same as `final3`. |
| `run5` | `change-card --kit-plugin`, a probe case whose prompt starts "Use the change-card skill to..." (not in the repo) | 0.007 | `works`: with 1.00, without 0.00 | The skill was invoked as `metodo:change-card`, its tool answered from the plugin alone, the validator passed and the judge accepted both expectations. |

## What these runs prove, all Tested with n=1

- The cascade, the script validators, the anti-cheat check, the verdict and the cache run end to end on the
  native tool, from a skill's own package and from the kit plugin.
- A script validator caught a wrong output file that the native graders passed (`run1`).
- From the kit plugin alone, the kit's MCP server starts and answers a tool call (`final3`, `run4`, `run5`).
  With a prompt that names the skill, a skill that needs the server works from that plugin (`run5`).

## What they do not prove

- That either skill is good or bad. `post-review-comment` got three different outcomes in three runs.
- Why `change-card` does not trigger on a prompt a user would type: in four runs and two forms the model went
  straight to the validator tool. Its description, or offering the tool beside the skill, needs a look.
