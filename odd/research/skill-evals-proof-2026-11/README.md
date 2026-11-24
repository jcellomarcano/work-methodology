# Skill evals: the first real runs

Date 2026-11-24. Branch `feat/skill-evals`, task T4 of `odd/tasks/skill-evals.md`. Three invocations of
`08-benchmark/lib/skill_eval.py run --real --runs 1 --model haiku --judge-model haiku --max-cost-usd 0.25`,
USD 0.031 in all. One run per arm, so every verdict below is a signal, not a result. The files beside this one
are the runner's own output with machine paths replaced by `<tmp>`, `<home>` and `<tmp-path>`.

| Run | Skill and flags | Verdict | What it showed |
|---|---|---|---|
| 1 | `post-review-comment` | `review`: its output fails a validator | `posted.md` did not match what `review_comment_post.py render` prints (bold labels missing). The native tool alone scored this run 1.0. |
| 2 | `change-card --kit-mcp` | `review`: it does not trigger when it should | With the kit's server started, the model called the validator tool directly and never invoked the skill. |
| 3 | `post-review-comment --no-cache` | `not measured` | The run with the skill timed out after 240 s; three of its shell calls had errored. Cause unknown. |

Two more invocations on 2026-11-24, task T5, USD 0.015, the skill loaded from the kit plugin (`--kit-plugin`), the
plugin's own MCP server started by Claude Code:

| Run | Case | Verdict | What it showed |
|---|---|---|---|
| 4 | the seed case of `change-card` | `review`: it does not trigger when it should | The plugin's server answered `mcp__plugin_metodo_metodo__change_card_validate`; the model never invoked the skill, as in run 2. |
| 5 | the same card and scorers, prompt starting "Use the change-card skill to..." (a probe case, not in the repo) | `works`: with 1.00, without 0.00 | The skill was invoked as `metodo:change-card`, its tool answered from the plugin alone, the validator passed and the judge accepted both expectations. |

Run 5 is the proof S13 asks for: a skill that needs the server, loaded from the kit plugin alone, called one of
its tools and got an answer. The plugin of these two runs differs from the final zip in two packed files edited
afterwards, neither on the path the runs exercised [Inferred].

What these runs prove about the tool, all Tested with n=1:

- The cascade, the script validators and the verdict run end to end on the native tool, and nothing is published.
- A script validator catches a wrong output file that the native graders pass.
- `--kit-mcp` starts this checkout's MCP server for the run and the skill's tools appear under the plugin's
  names (`mcp__plugin_change-card_metodo__change_card_validate`).

What they do not prove: that either skill is good or bad. Three runs per arm is the floor for a verdict
(`odd/tasks/skill-evals.md`, S7), and that run is the owner's spend decision (S11).
