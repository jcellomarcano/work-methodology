# Skill evals: does this skill work?

One command answers it per skill: `works`, `review` or `not measured`, and why. It runs fixed cases with and without the skill on Claude Code's own eval tool, `claude plugin eval`, and scores them itself. Nothing is spent without `--real`.

All 17 skills have a BUILD and a case [Tested: `03-tools/bin/skill-build.sh test --all`]. At five runs per arm seven read `works` and ten read `review` (section 6). The whole kit against plain Claude Code is another instrument: [09-measurement.md](09-measurement.md). Tags, from `08-benchmark/METRICS.md`: **Measured**, **Tested**, **Inferred**, **Assumed**, **Unknown**.

## 1. The two files you write

| | BUILD | Case |
|---|---|---|
| File | `02-skills/<skill>/BUILD.json`, one per skill | `08-benchmark/evals/<skill>/<case>/case.json`, any number |
| It says | what the skill ships and what it needs from the kit | one task, and how its result is checked |
| Checked by | `03-tools/bin/skill-build.sh test` | `08-benchmark/lib/skill_eval.py validate` |

## 2. A BUILD

Every skill declares the same five targets. To write one, copy `02-skills/change-card/BUILD.json` and edit `deps`.

| Target | PASS when | SKIP when |
|---|---|---|
| `agent_skill` | every file in `srcs` exists, and `deps` names the MCP tools of the skill's `allowed-tools` line plus each kit file the skill calls | never |
| `validate_skill_test` | the front matter is well formed and `name` is the folder | never |
| `py_type_test` | a strict type check accepts the skill's Python | the skill has no Python, or no checker is installed |
| `py_test` | the declared unittest modules pass | none is declared |
| `eval_suite` | every case of the skill is valid | the skill has no case |

A SKIP is never a pass. `srcs` are top-level files: a nested path is refused until the installers can copy a subfolder [Tested].

```bash
03-tools/bin/skill-build.sh test --all                    # per target: PASS, FAIL or SKIP and why
03-tools/bin/skill-build.sh test change-card --no-cache   # one skill, no cache
03-tools/bin/skill-build.sh build change-card             # the zip, in the tools folder's out/skill-build/dist/
```

The zip is the plugin the eval runs, so what is measured is what ships. `BUILD.json` is neither packed nor installed.

## 3. A case

| Piece | What it is |
|---|---|
| `prompt.md` | what a user would type; it does not name the skill |
| `case.json` | the tier (`smoke`, `core`, `deep`), `expected_skills`, `setup.files`, `validators`, `expectations` and the limits |
| `setup/` | fixed files the run starts from |
| `testdata/` | the answer key: never given to the run; a run that reads it is `cheated` |
| `validators/` | scripts that compare the files the run left with `testdata/`; exit 0 passes |
| `mocks/` | optional `mocks/metodo/<tool>.md`, the eval tool's own format: what the kit tool answers in both arms, no real server; a server flag drops it |

To write one, copy `08-benchmark/evals/post-review-comment/smoke-render/`. Run the validator by hand on a wrong file first: a case that cannot fail measures nothing.

## 4. The commands

```bash
08-benchmark/bin/skill-eval.sh list             # each skill, its cases and tiers
08-benchmark/bin/skill-eval.sh validate         # every case is valid
08-benchmark/bin/skill-eval.sh run change-card  # its plan; several names, or --all
08-benchmark/bin/skill-eval.sh run change-card --kit-mcp --real --max-cost-usd 0.25
08-benchmark/bin/skill-eval.sh report           # the verdicts from stored results
```

- `--real` is the only flag that spends. It prints its ceiling first; the default is USD 0.50 per skill [Measured: `08-benchmark/lib/skill_eval_run.py`].
- `--kit-mcp` starts this checkout's MCP server for a skill that declares its tools; 14 of the 17 do [Measured: the `deps` of each `BUILD.json`]. It runs as you, outside the tool's sandbox. Without it or a mock such a skill has no tools and is never `works`. With it or `--kit-plugin` (section 8) the tool runs twice on one ceiling: the arm without the skill is the same plugin less the skill's folder, so it keeps the server.
- A case reruns only when its files, the skill's, the kit plugin's or the settings (model, judge, runs, server, form) change; `--no-cache` forces it.

## 5. Reading the verdict

Each run passes three scorers in order: the skill was invoked, the validators pass, an independent model accepts the answer. A later scorer counts only when the earlier ones passed.

| The report says | It means | What to do |
|---|---|---|
| `works`: the result is better than without it | it triggered, and passed more often than the runs without it | keep it; confirm with `--runs 3` |
| `review`: it does not trigger when it should | the agent never called the skill | rewrite the `description` in its `SKILL.md` |
| `review`: changes nothing | the same score with and without it | shrink or cut the skill, or make the case harder |
| `review`: the result is worse than without it | the skill hurts on this case | read the run's line under the case, fix the steps |
| `review`: its output fails a validator | the files it left are wrong | fix the skill, or a too strict validator |
| `review`: the judge rejects it | the answer misses an expectation | fix the skill's output, or reword the expectation |
| `not measured` | nothing stored, the run failed, every run cheated, or it ran without its MCP tools | the reason names what to run next |

`[signal]` beside a verdict means fewer than three scored runs per arm. The limits are a trigger, validator and judge rate of 0.8 and a difference of 0.1 [Measured: `THRESHOLDS` in `08-benchmark/lib/skill_eval_run.py`]. A run that did not pass lists the tools it called: its trace is deleted once scored.

## 6. What a run costs, and what leaves your machine

| Run, model and judge `haiku` | USD | Verdict |
|---|---|---|
| the 17 skills, one case each, five per arm | 1.42 | 7 `works`; 10 `review`: 3 do not trigger, 5 trigger and fail, 2 do no better than without |
| `change-card/smoke-missing-field` alone, five per arm | 0.060 | `works`: with 0.80, without 0.00 |
| the same case at three per arm, twice | 0.037, 0.033 | `works`, then `review` [signal]: a split judge vote rejected one right answer |

Source: the `spend:` line of each run, 2026-11-24, kept in `odd/research/skill-evals-bench-2026-11/`, whose README has the table per skill [Tested]. One run per arm cost USD 0.007 to 0.013. The tool checks the ceiling before each run, so the run in flight may pass it.

The eval tool publishes its HTML report to claude.ai by default. The kit passes `--no-publish` on every command line; a test fails if it is missing [Tested: `08-benchmark/tests/test_skill_eval_run.py`]. Never call `claude plugin eval` by hand without it. Each run is a Claude Code session on your own credential; results stay under the tools folder's `out/skill-evals/`.

## 7. What is not measured yet

| Gap | State | Tag |
|---|---|---|
| A verdict beyond one case | every skill has one case, run on one model, `haiku` | Measured |
| A steady verdict at three runs | 0.8 then needs three of three, so one judge vote flips it; five runs held for `change-card` | Tested |
| Live tool calls and role agents | a run's folder is no git repository and a package carries no role agent, so cases stage real script output and start mid-skill | Tested |
| `--kit-plugin` with the server in both arms | proven in stub tests only; `--kit-mcp` has a real run | Unknown |
| Why three skills do not trigger | their cases start after the step their descriptions name | Inferred |
| Why the shell calls of `post-review-comment` failed | a stored result keeps tool names, not commands | Unknown |
| Strict typing of a skill's Python | no checker installed; the three command lines in `03-tools/lib/skill_build.py` are unverified | Measured |
| Any runtime but Claude Code | the eval tool is Claude Code's own | Measured |
| A forbidden file read unseen | `cheated` needs a call naming it or a result showing a line of it, 12+ characters; a count or a hash is not seen | Tested |
| A tier as "at least" | `--tier` is an exact match: `core` does not include `smoke` | Measured |

## 8. The kit plugin

The package per skill stays the unit verified and evaluated, but carries no server, which 14 of the 17 skills call. One more target packs the kit as one plugin, `metodo`: every skill, the server under `tools/`, and each tool name as that plugin exposes it. Use it to hand the skills over, or to measure a skill as it ships (`run --kit-plugin`; the report names the form). Limits: the server writes under the plugin's `tools/out`, which Claude Code replaces on an update, and no single setting moves it [Measured: `03-tools/mcp/registry.py`]; its config is the kit's default; hooks and role agents are not in it; it is published nowhere.

```bash
03-tools/bin/skill-build.sh build --kit-plugin --out <dir>   # <dir>/metodo/: the zip (same bytes each time) and marketplace/
claude plugin validate <dir>/metodo/marketplace/plugins/metodo --strict
claude plugin marketplace add <dir>/metodo/marketplace && claude plugin install metodo@metodo-kit   # the user's two; the kit never runs them
```
