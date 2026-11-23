# Skill evals: does this skill work?

One command answers it per skill: `works`, `review` or `not measured`, with the reason in plain words. It runs fixed cases with the skill and without it on Claude Code's own eval tool, `claude plugin eval`, and scores them itself. Nothing is spent unless you pass `--real`.

Two skills have a case today. Their first runs read `review` at one run per arm, which is a signal and not a verdict (section 6). This page says what a BUILD and a case are, how to write one, the commands, how to read a verdict, what a run costs and what is not measured. Comparing the whole kit with plain Claude Code is another instrument: [09-measurement.md](09-measurement.md).

Tags are the ones of `08-benchmark/METRICS.md`: **Measured**, **Tested**, **Inferred**, **Assumed**, **Unknown**.

## 1. The two files you write

| | BUILD | Case |
|---|---|---|
| File | `02-skills/<skill>/BUILD.json`, one per skill | `08-benchmark/evals/<skill>/<case>/case.json`, as many as you want |
| It says | what the skill ships and what it needs from the kit | one task, and how its result is checked |
| Checked by | `03-tools/bin/skill-build.sh test` | `08-benchmark/lib/skill_eval.py validate` |
| Spends | nothing | nothing until `run --real` |

All 17 skills have a BUILD; 2 have a case [Tested: `03-tools/bin/skill-build.sh test --all`, 2026-11-24].

## 2. A BUILD

It declares the same five targets in every skill. To write one, copy `02-skills/change-card/BUILD.json` and edit `deps`.

| Target | PASS when | SKIP when |
|---|---|---|
| `agent_skill` | every file in `srcs` exists, and `deps` names the MCP tools of the skill's `allowed-tools` line plus each kit file the skill calls | never |
| `validate_skill_test` | the front matter is well formed and `name` is the folder | never |
| `py_type_test` | a strict type check accepts the skill's Python | the skill has no Python, or no checker is installed |
| `py_test` | the declared unittest modules pass | none is declared |
| `eval_suite` | every case of the skill is valid | the skill has no case |

A SKIP is never a pass. `srcs` are top-level files: the installers cannot copy a subfolder yet. No type checker was installed where this was written, so no strict check has ever run [Measured: `odd/tasks/skill-evals.md`, S12].

```bash
03-tools/bin/skill-build.sh test --all                    # one line per target: PASS, FAIL or SKIP with its reason
03-tools/bin/skill-build.sh test change-card --no-cache   # one skill, nothing taken from the cache
03-tools/bin/skill-build.sh build change-card             # the zip, under the tools folder's out/skill-build/dist/
```

The zip is the plugin the eval runs, so what is measured is what ships. `BUILD.json` is neither packed nor installed.

## 3. A case

| Piece | What it is |
|---|---|
| `prompt.md` | what a user would type; it does not name the skill |
| `case.json` | the tier (`smoke`, `core`, `deep`), `expected_skills`, `setup.files`, `validators`, `expectations` and the limits |
| `setup/` | fixed files the run starts from |
| `testdata/` | the answer key: never given to the run, and a run that reads it is `cheated` |
| `validators/` | scripts that compare the files the run left with `testdata/`; exit 0 passes |

To write one, copy `08-benchmark/evals/post-review-comment/smoke-render/`. Run the validator by hand on a wrong file first: a case that cannot fail measures nothing. Keep `expectations` to one or two sentences a stranger could check.

| Seed case | The user asks to | It fails when |
|---|---|---|
| `post-review-comment/smoke-render` | render a linted review comment as it will be posted | `posted.md` is missing, or any line differs from the script's rendering |
| `change-card/smoke-missing-field` | validate a card that lacks one field | `card-verdict.json` is missing, or its `verdict`, `routing` or `fields_missing` differ from the validator's |

## 4. The commands

```bash
python3 08-benchmark/lib/skill_eval.py validate            # every case is well formed; spends nothing
python3 08-benchmark/lib/skill_eval.py run --tier smoke    # the plan and its cost ceiling; spends nothing
python3 08-benchmark/lib/skill_eval.py run --skill change-card --kit-mcp --real --max-cost-usd 0.25
python3 08-benchmark/lib/skill_eval.py report              # the verdicts from the stored results; spends nothing
```

- `--real` is the only flag that spends. The run prints its ceiling first; the default is USD 0.50 per skill [Measured: `08-benchmark/lib/skill_eval_run.py`].
- `--kit-mcp` starts this checkout's MCP server for a skill that declares its tools. The server runs as you, outside the tool's sandbox. Without it such a skill runs without its tools, the plan and the report say so, and its verdict is never `works`. 14 of the 17 skills declare tools [Measured: the `deps` of each `BUILD.json`].
- A case is not run again while its files, the skill's files and the settings (model, judge, runs, server) stay the same. `--no-cache` runs it anyway.

## 5. Reading the verdict

Each run passes three scorers in order: the skill was invoked, the validators pass, an independent model accepts the answer. A later scorer counts only when the earlier ones passed.

| The report says | It means | What to do |
|---|---|---|
| `works`: the result is better than without it | it triggered, and passed more often than the runs without it | keep it; ask for three runs with `--runs 3` |
| `review`: it does not trigger when it should | the agent never called the skill | rewrite the `description` in its `SKILL.md` |
| `review`: changes nothing | the same score with and without it | shrink or cut the skill, or make the case harder |
| `review`: the result is worse than without it | the skill hurts on this case | read the run's line under the case, fix the steps |
| `review`: its output fails a validator | the files it left are wrong | fix the skill, or a validator that is too strict |
| `review`: the judge rejects it | the answer misses an expectation | fix the skill's output, or reword the expectation |
| `not measured` | nothing stored, the run failed, every run cheated, or it ran without its MCP tools | the reason names what to run next |

`[signal]` beside a verdict means fewer than three runs per arm. The limits are a trigger, validator and judge rate of 0.8 and a difference of 0.1 [Measured: `THRESHOLDS` in `08-benchmark/lib/skill_eval_run.py`]. A run that did not pass lists the tools it called, since its trace is deleted once scored.

## 6. What a run costs, and what leaves your machine

| Run, one per arm, model and judge `haiku` | USD | Verdict |
|---|---|---|
| `post-review-comment/smoke-render` | 0.011 | `review`: its output fails a validator (bullets without the script's bold labels) |
| the same case, run again | 0.013 | `not measured`: the run with the skill hit the case's 240 s limit; 3 of its 6 shell calls came back as errors |
| `change-card/smoke-missing-field`, with `--kit-mcp` | 0.007 | `review`: it does not trigger when it should |

Source: the `spend:` line of each run, 2026-11-24, logged in `odd/tasks/skill-evals.md` [Tested, n=1 each; the repeat shows how far one run is from a verdict]. A larger model or more turns costs more [Unknown: how much]. The tool checks the ceiling before each run, so the run in flight may pass it.

The eval tool publishes its HTML report to claude.ai by default. The kit passes `--no-publish` on every command line, and a test fails if that flag is ever missing [Tested: `08-benchmark/tests/test_skill_eval_run.py`]. Never call `claude plugin eval` by hand without it. Each run is a Claude Code session on your own credential; results stay under the tools folder's `out/skill-evals/`.

## 7. What is not measured yet

| Gap | State | Tag |
|---|---|---|
| A verdict, not a signal | no case has run three times per arm; that spend is the owner's decision | Measured |
| 15 of the 17 skills | they have no case | Measured |
| The skill apart from its tools | with `--kit-mcp` the arm without the skill also loses the server, so the difference is the skill plus its tools | Inferred |
| Why `change-card` did not trigger | the run called the server's tool directly and never the skill, once | Tested, n=1 |
| Why the shell calls of `post-review-comment` failed | the stored result keeps the names of the tools a run called, not its commands; the skill's script sits in the kit, outside the folder the tool confines shell calls to | Unknown |
| Strict typing of a skill's Python | no checker installed; the three command lines in `03-tools/lib/skill_build.py` are unverified | Measured |
| A skill with a subfolder | a nested `srcs` path is refused until the installers can copy one | Tested |
| Any runtime but Claude Code | the eval tool is Claude Code's own | Measured |
| A tier as "at least" | `--tier` is an exact match: `core` does not include `smoke` | Measured |
