# Measurement: is the kit good for us?

Nobody can tell you yet, and the kit says so. It ships the instrument to find out on your own repo. No A/B run with repetitions has been executed on a real repo, and the seeded-defect phase has zero runs [Measured: `odd/research/kit-audit-2026-11/audit.md`, section 4]. The only comparison on file is one pilot pull request. That is a signal, not a conclusion.

This page says what to compare, what the kit records by itself, how to run the comparison, how to read it and what it costs. Adoption steps are in [07-adoption.md](07-adoption.md).

Every statement carries a tag (`08-benchmark/METRICS.md`): **Measured** (read from a record), **Tested** (produced by running something), **Inferred** (derived by a stated rule), **Assumed** (not derived from evidence), **Unknown** (no source).

## 1. What is compared

Two ways of working, both with agents. A no-AI arm is not offered: the audit cites METR reporting that developers refuse it [Inferred: audit, section 8]. An **arm** is one named setup that runs the same tasks. The flag `--preset kit-vs-vanilla` gives four [Measured: `08-benchmark/lib/bench_ab.py`]:

| Arm | Setup |
|---|---|
| `vanilla` | Claude Code with no kit file, no skills and no MCP server |
| `kit-neutral` | The kit copied in, a neutral prompt. It answers: does the kit start by itself? |
| `kit-invoked` | The kit copied in, and the prompt asks for the kit's review |
| `native` | Claude Code's own `code-review` skill |

The benchmark measures the kit as a bundle (hooks, skills, agents, MCP tools and prompt together), not each part [Inferred: audit, section 4]. It measures Claude Code sessions only [Measured: `02-skills/harness-benchmark/SKILL.md`].

## 2. The baseline the kit records by itself

This costs no model spend. It starts at install (step 1 of adoption).

| Record | Written by | File | What it gives you |
|---|---|---|---|
| Adoption record | `init.sh`, step `bench`, once | `<instance>/out/bench/adoption.json` | The install time: the line between before and after |
| Session rows | a SessionEnd hook queues each finished session; `bench.sh collect` measures it | `<instance>/out/bench/sessions/<id>.json` | One row per session: counts and lengths, never prompt or reply text |
| Phase 1 report | `bench.sh report` | `<instance>/out/bench/report/phase1-baseline.md` | Medians before and after adoption, each with its n and its tag |

```bash
<instance>/bin/bench.sh status <repo>     # adoption, sessions_measured, kit_sessions, queue_left; measures nothing
<instance>/bin/bench.sh collect <repo>    # prints failed, measured, queue_left, skipped
<instance>/bin/bench.sh report <repo>     # collect, then the phase 1 report
python3 02-skills/harness-benchmark/bench.py session --project <repo> --out <dir>   # same reading without an instance
```

Read a before and after as a hypothesis, never as a cause. Task mix, model versions and the team's own practice drift over the period (`08-benchmark/reports/phase1-baseline.md`) [Inferred]. The doctor checks `bench.wired` and `bench.used` say whether sessions are queued and how many are stored. `init.sh --no-bench` skips the record at install; `bench.enabled: false` in the instance config stops measuring [Measured: `03-tools/lib/doctor.py`, `03-tools/lib/init_kit.py`].

## 3. The A/B protocol

Run the commands from a clone of the kit. In a repo with an instance, `<instance>/bin/bench.sh ab <repo> run|judge|report` forwards to the same code [Measured: `03-tools/bin/bench.sh`]. The rules in the second table were read in `08-benchmark/lib/bench_ab.py`, `08-benchmark/protocols/ab-config.example.json` and `02-skills/harness-benchmark/SKILL.md`.

| # | Step | Command or file |
|---|---|---|
| 1 | Write the plan before any run: tasks from your own work, arms, `k`, one `model`, one `effort`, your margin (section 5) | copy `08-benchmark/protocols/ab-config.example.json` to `ab.json` |
| 2 | Print the planned runs. It spends nothing | `python3 02-skills/harness-benchmark/bench.py ab --config ab.json --preset kit-vs-vanilla --dry-run` |
| 3 | The owner approves the spend (section 6) | a written yes |
| 4 | Run every task under every arm, `k` times | the same command with `--out <run>` instead of `--dry-run`; `<run>` must be outside the repo |
| 5 | Judge: seeded defects first, then blind pairwise judges in both orders | `python3 02-skills/harness-benchmark/bench.py judge --run <run>` |
| 6 | Report | `python3 02-skills/harness-benchmark/bench.py report --run <run>` writes `<run>/report.md` and `<run>/report.json` |

| Rule | Who enforces it | Tag |
|---|---|---|
| One model and one effort for every arm | the config loader | Measured |
| Each run gets a fresh worktree outside the repo; your working tree is never written | the runner | Measured |
| A kit run with no trace of the kit in its transcript is `invalid-arm`: listed, never scored | the arm's `evidence` pattern | Measured |
| Comparisons are computed only against arms named `vanilla` or `native` | the report | Measured |
| At least three repetitions (`k` defaults to 3; the code accepts 1) | you; the skill escalates `k` below 3 to the owner | Measured |
| At least five tasks | you; below five the report prints the signal line | Measured |
| Judges from two model families | you; one family is allowed and reported as a limitation | Measured |

## 4. Headline metrics and where each number comes from

| Metric | Field in `report.json` | Source | Tag the report gives |
|---|---|---|---|
| Activation: share of an arm's runs where its setup really ran | `activation` | the transcript matches the arm's `evidence` pattern | Measured; Unknown when the arm has no pattern |
| Spend, and cost per solved task | `spend_usd`, `cost_per_solved_usd` | `total_cost_usd` of each `claude -p` run; timed-out runs with no cost are counted beside it | Measured |
| Task success, one run and all `k` runs | `pass_at_1`, `pass_hat_k` | the task's `verify` command exits 0 | Tested |
| Stability | `flip`, `flip_rate` | the outcome differs across the `k` repetitions | Measured |
| Seeded-defect recall by severity | `seeded_recall` | a finding matches a defect you planted, on file, line window and category | Tested |
| Share of findings judged valid | `judge_validity` | the judges' verdict per finding | Measured when the judges agree (kappa at least 0.6), else Inferred |

Lead with activation, spend, cost per solved task and seeded recall [Measured: `02-skills/harness-benchmark/SKILL.md`]. Report success as a check, not as the headline: a design of 10 to 50 tasks resolves only large differences [Assumed: `odd/research/benchmark-landscape/report.md`].

## 5. The decision rule

This is what the report code applies [Measured: `build_report` in `08-benchmark/lib/bench_ab.py`]. It compares `pass_at_1`, `cost_per_run_usd` and `judge_validity`. The interval is a paired bootstrap over tasks, 95%, 10,000 resamples by default, with a fixed seed.

| Situation | The report prints | What you may say |
|---|---|---|
| The interval of the difference does not include zero | `shown` | There is a difference on these tasks. Why is still Inferred |
| The interval includes zero | `not shown` | Nothing, in either direction |
| Fewer than two tasks in the comparison | `not shown (n tasks < 2)` | Nothing |
| `k` is 1, or fewer than five tasks | `signal, not a conclusion` at the top | A signal worth a second run |

- **Quote n beside every comparison.** Each row carries `n_tasks` and `n_runs`.
- **Non-inferiority is your frame, not the code's.** Before the run, write the margin: the kit passes if its success is not worse than `vanilla` by more than that margin, and its extra cost is the price of the recall it adds [Inferred: audit, section 8]. The code has no margin key. You compare the lower end of the interval to your margin by hand [Measured].
- **One run is a signal.** In a study of 60,000 agent runs, picking a different single run moved the score by 2.2 to 6.0 points [Measured there, cited in `odd/research/benchmark-landscape/report.md`; not re-fetched here].
- **Three repetitions is a floor, not a guarantee.** The audit states that its sample sizes are the researcher's own calculation, not a published threshold.

## 6. What a run costs

The owner approves the spend before any `ab` run [Measured: `02-skills/harness-benchmark/SKILL.md`]. Runs = tasks × arms × `k`, and each run is a full `claude -p` session. The dry run prints the number of runs and `estimated cost: unknown until the first run`.

| Per run, on one pull request (28 files, one repetition) | USD |
|---|---|
| `vanilla` review | 1.34 |
| Kit review, invoked | 8.38, that is 6.3 times vanilla |
| Claude Code `code-review` skill | 2.25 |
| One blind judgment | 0.63 |

Source: `08-benchmark/reports/pilot-pr176.md` [Measured, n=1, the kit's own run]. The seeded-defect protocol forecasts USD 550 to 880 for its full design, and USD 250 to 400 for 48 runs (`08-benchmark/protocols/phase2-protocol.md`, section 6) [vanilla Measured on that one pull request; kit Assumed]. Each run leaves a transcript under `~/.claude/projects/`; delete it if the prompts are sensitive.

## 7. What you cannot measure yet

| Gap | State in this tree | Tag |
|---|---|---|
| A repeated A/B on a real repo | none run; `08-benchmark/reports/` holds the phase 1 reports and one pilot pull request | Measured |
| Seeded-defect recall | the matcher exists (`seeded` in the config); no seeded task set ships and no run exists | Measured |
| Any runtime but Claude Code | not measured | Measured |
| A team in one report | the collector reads one user's transcripts folder; nothing aggregates engineers | Measured: `03-tools/lib/bench_collect.py` |
| A second judge family | the config accepts one; the example ships one family, and every judgment so far is same-family | Measured in `odd/research/benchmark-landscape/report.md` on 2026-10-20 |
| A non-inferiority verdict | no margin in the code (section 5) | Measured |
| Rework, escaped defects, lead time | the A/B report has no such field | Measured |
| The effect of one part of the kit | arms change the whole bundle; per skill: [11-skill-evals.md](11-skill-evals.md) | Inferred |
| Whether a hook's blocks are right | only after the owner marks false positives ([07-adoption.md](07-adoption.md), step 2) | Measured |
