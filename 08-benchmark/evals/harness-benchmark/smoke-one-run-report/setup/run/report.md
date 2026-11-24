# A/B benchmark report

Commit `4c1e9a7b2d35` · model sonnet · effort medium · k 1 · seed 7 · bootstrap 2000 resamples · cost source: claude -p total_cost_usd

n: 4 tasks, 12 runs (invalid-arm 4, ok 8)

**signal, not a conclusion** (k == 1 or fewer than 5 tasks)

## Per arm and task

| arm | task | scored/runs (excluded) | pass@1 | pass^k | flip | cost/run USD | spend USD | cost/solved USD | findings | judge validity | status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| kit-invoked | t1 | 1/1 (0 excluded) | 1.0 [Tested] | 1 [Tested] | Unknown (not-run) | 0.9725 [Measured] | 0.9725 [Measured] | 0.9725 [Measured] | 0.0 [Measured] | Unknown (not-run) | ok |
| kit-invoked | t2 | 1/1 (0 excluded) | 1.0 [Tested] | 1 [Tested] | Unknown (not-run) | 0.8846 [Measured] | 0.8846 [Measured] | 0.8846 [Measured] | 0.0 [Measured] | Unknown (not-run) | ok |
| kit-invoked | t3 | 1/1 (0 excluded) | 1.0 [Tested] | 1 [Tested] | Unknown (not-run) | 1.0513 [Measured] | 1.0513 [Measured] | 1.0513 [Measured] | 0.0 [Measured] | Unknown (not-run) | ok |
| kit-invoked | t4 | 1/1 (0 excluded) | 0.0 [Tested] | 0 [Tested] | Unknown (not-run) | 1.1379 [Measured] | 1.1379 [Measured] | Unknown (not-run) | 0.0 [Measured] | Unknown (not-run) | ok |
| kit-neutral | t1 | 0/1 (1 excluded) | Unknown (invalid-arm) | Unknown (invalid-arm) | Unknown (not-run) | Unknown (invalid-arm) | Unknown (not-run) | Unknown (not-run) | Unknown (not-run) | Unknown (not-run) | invalid-arm |
| kit-neutral | t2 | 0/1 (1 excluded) | Unknown (invalid-arm) | Unknown (invalid-arm) | Unknown (not-run) | Unknown (invalid-arm) | Unknown (not-run) | Unknown (not-run) | Unknown (not-run) | Unknown (not-run) | invalid-arm |
| kit-neutral | t3 | 0/1 (1 excluded) | Unknown (invalid-arm) | Unknown (invalid-arm) | Unknown (not-run) | Unknown (invalid-arm) | Unknown (not-run) | Unknown (not-run) | Unknown (not-run) | Unknown (not-run) | invalid-arm |
| kit-neutral | t4 | 0/1 (1 excluded) | Unknown (invalid-arm) | Unknown (invalid-arm) | Unknown (not-run) | Unknown (invalid-arm) | Unknown (not-run) | Unknown (not-run) | Unknown (not-run) | Unknown (not-run) | invalid-arm |
| vanilla | t1 | 1/1 (0 excluded) | 1.0 [Tested] | 1 [Tested] | Unknown (not-run) | 0.4137 [Measured] | 0.4137 [Measured] | 0.4137 [Measured] | 0.0 [Measured] | Unknown (not-run) | ok |
| vanilla | t2 | 1/1 (0 excluded) | 0.0 [Tested] | 0 [Tested] | Unknown (not-run) | 0.3891 [Measured] | 0.3891 [Measured] | Unknown (not-run) | 0.0 [Measured] | Unknown (not-run) | ok |
| vanilla | t3 | 1/1 (0 excluded) | 1.0 [Tested] | 1 [Tested] | Unknown (not-run) | 0.4462 [Measured] | 0.4462 [Measured] | 0.4462 [Measured] | 0.0 [Measured] | Unknown (not-run) | ok |
| vanilla | t4 | 1/1 (0 excluded) | 0.0 [Tested] | 0 [Tested] | Unknown (not-run) | 0.5208 [Measured] | 0.5208 [Measured] | Unknown (not-run) | 0.0 [Measured] | Unknown (not-run) | ok |

## Activation and stability

| arm | activation | n runs | flip rate | n tasks |
|---|---|---|---|---|
| kit-invoked | 1.0 [Measured] | 4 | Unknown (not-run) | 0 |
| kit-neutral | 0.0 [Measured] | 4 | Unknown (not-run) | 0 |
| vanilla | Unknown (not-run) | 4 | Unknown (not-run) | 0 |

## Comparisons (paired task-level bootstrap 95% CI)

| metric | arm | vs | n tasks | n runs | diff | 95% CI | reading |
|---|---|---|---|---|---|---|---|
| pass_at_1 | kit-neutral | vanilla | 0 | 0 | Unknown (not-run) | Unknown | not shown |
| pass_at_1 | kit-invoked | vanilla | 4 | 8 | 0.25 [Measured] | [0.0, 0.75] | not shown |
| cost_per_run_usd | kit-neutral | vanilla | 0 | 0 | Unknown (not-run) | Unknown | not shown |
| cost_per_run_usd | kit-invoked | vanilla | 4 | 8 | 0.569125 [Measured] | [0.5229, 0.6111] | shown |
| judge_validity | kit-neutral | vanilla | 0 | 0 | Unknown (not-run) | Unknown | not shown |
| judge_validity | kit-invoked | vanilla | 0 | 0 | Unknown (not-run) | Unknown | not shown |

## Runs not scored

| task | arm | rep | status | reason |
|---|---|---|---|---|
| t1 | kit-neutral | 0 | invalid-arm | evidence-missing |
| t2 | kit-neutral | 0 | invalid-arm | evidence-missing |
| t3 | kit-neutral | 0 | invalid-arm | evidence-missing |
| t4 | kit-neutral | 0 | invalid-arm | evidence-missing |
