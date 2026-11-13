# Adoption

Adopt the kit in five steps. Each step ends with a check you can run or a file you can open, never with an opinion. You can stop after any step, and you can back out with one command.

- Is it good for us? Read the [measurement runbook](09-measurement.md).
- Where does it stand against other tools? Read [position](10-position.md).

| Term | Meaning |
|---|---|
| Kit | A clone of this repository. Commands that start with `03-tools/` run from its root. |
| Instance | The per-project copy of `03-tools/` that holds your project's config and outputs. It lives outside your repo: `init.sh` creates it at `~/<repo_name>-tools` unless `--instance` says otherwise. |
| Hook | A script the agent runtime calls around a tool call. It lets the call pass, warns, or blocks. |
| Ledger | The file where each hook decision is written, one line each: `<instance>/out/hooks/<session>/ledger.jsonl`. |
| Receipt | The record that ties one review to one exact tree: `<instance>/out/rdd/<tree_sha>.receipt.json`. |
| Warn, block | In warn mode a hook writes its ledger line and lets the call pass. In block mode it denies or asks. |

## The five steps

| Step | When | Who | What the team does | Exit check |
|---|---|---|---|---|
| 0. Rules only | day 1 | team lead, every engineer | Adds `AGENTS.md` and a context pack to the repo, tags claims with the five evidence tags, writes one change card per change from `04-templates/change-card.md`. Installs nothing. | `change_card_validator.py` exits 0 on the card of every pull request. |
| 1. Wired, warn mode | week 1 | one engineer; the owner fills the pending steps `init.sh` lists | Runs `init.sh`. Hooks only write the ledger. | `doctor.sh` exits 0 and its `bench.wired` check is PASS. `bench.sh status` prints an `adoption` record and, after a week of work, `sessions_measured` above 0. |
| 2. Calibrate | weeks 2-3 | team lead | Reads the hooks report, marks each wrong hook decision as a false positive, fixes the config. | `hooks_report.py --verdicts` prints `fires` and `false_positives` for every element the team wants to block, and the team has written down the false-positive limit it accepts. |
| 3. Block what earned it | week 4 | the owner decides; one engineer edits | Sets `rdd.hook_modes` to `block`, one hook per change, the launch gate `guard_spawn` included. | `<instance>/config/project.json` names each promoted hook, and the next `--verdicts` run shows its `false_positives` at or under the limit. |
| 4. Full loop on critical paths | month 2 | authors and reviewers; the owner at every gate | Opens a receipt per candidate (`receipt-review` skill), runs the two adversaries where the tier asks (`adversarial-round` skill), benchmarks each release. | A receipt file exists for the tree of every merge that touched a path in `critical_paths`. `hooks_report.py` counts them under `receipts.by_tier` and `receipts.by_verdict`. |

The steps and their timing come from `odd/research/kit-audit-2026-11/audit.md`, section 8. The timing is a proposal, not a measured result [Assumed]. Every command, flag and field on this page was read in this tree [Measured].

```bash
# Step 0, from a clone of the kit; nothing is installed in your repo
python3 03-tools/lib/change_card_validator.py <card.md>      # exit 1 when the card fails

# Step 1
03-tools/bin/init.sh <repo> --dry-run                        # the plan; writes nothing
03-tools/bin/init.sh <repo>                                  # instance, install, baseline, adoption record, doctor, smoke
03-tools/bin/doctor.sh <repo> --tools <instance>             # exit 0 means no FAIL
03-tools/bin/smoke-loop.sh <repo> --tools <instance>         # the review loop, on a throwaway clone
<instance>/bin/bench.sh status <repo>                        # adoption, sessions_measured, kit_sessions

# Step 2
python3 <instance>/lib/hooks_report.py                       # writes <instance>/out/hooks/report.json
<instance>/bin/mark-fp.sh <session> <seq> --reason "<why>"   # one ledger line was a false positive
python3 <instance>/lib/hooks_report.py --verdicts --as-of YYYY-MM-DD --format md

# Step 3, in <instance>/config/project.json:  "rdd": { "mode": "warn", "hook_modes": { "guard_spawn": "block" } }

# Step 4, before a release
<instance>/bin/benchmark-release.sh <repo> <refA> <refB>
```

## What to know before you block anything

- **Warn is the default.** The shipped config and the one `03-tools/bin/adopt.sh` writes set `rdd.mode` to `warn` (`03-tools/config/project.json`) [Measured]. A few rules block in every mode. The doctor proves one on your repo: its `hooks.fire` check passes only when a test `git push --force` is denied (`03-tools/lib/doctor.py`) [Measured].
- **Hooks fail open.** A hook that crashes lets the call pass (`03-tools/hooks/_common.py`) [Measured]. A missing ledger line does not prove the rule held.
- **Precision needs your marks.** `--verdicts` reports `precision` as null until at least one false positive is marked on that element, and says why under `not_measured` (`03-tools/lib/hooks_report.py`) [Measured]. Unmeasured is never shown as perfect.
- **A verdict is a recommendation.** `--verdicts` never changes the config. The owner does, with a change card.
- **Runtimes.** `init.sh` installs for Claude Code and pi, and for Antigravity with `--runtime agy`. Sessions are measured on Claude Code only (`03-tools/lib/init_kit.py`) [Measured]. Other harnesses: [08-harnesses.md](08-harnesses.md).

## Back out

Run `03-tools/bin/init.sh <repo> --uninstall --dry-run` to see the plan, then the same without `--dry-run`. Exit check: it exits 0, prints `kit_absent`, and writes `<instance>/out/uninstall/<repo_sha>.json`.

| What | After `--uninstall` |
|---|---|
| Kit files in your repo, byte-identical to what the kit installed | removed, listed under `removed` |
| Kit files you edited | kept, listed under `kept_modified`; delete them by hand |
| The instance (config, ledger, receipts, measured sessions) and the audit folder (`~/<repo_name>-audit`, where `init.sh` wrote your invariants and context pack scaffolds) | kept. `--purge` deletes them only when they hold nothing but what `init.sh` left; otherwise it refuses and lists why |
| What you added yourself, such as change cards | untouched |

Smaller steps back: remove a hook from `rdd.hook_modes` to return it to warn; set `bench.enabled` to `false` in the instance config to stop measuring sessions [Measured: `03-tools/lib/bench_collect.py`].

## Step checklist (the decisions only people can take)

- [ ] Declare your protected properties ranking ([docs/01-principles.md](01-principles.md)) (step 0)
- [ ] Write invariants and their guard mechanisms (step 0)
- [ ] List critical paths, the ones that trigger the High review tier (step 0)
- [ ] Pick or confirm risk-tier rules for your project (step 0)
- [ ] Define owner gates and an emergency lane (step 0)
- [ ] Copy `04-templates/` into your project (step 0)
- [ ] Run one real change through the full loop as a pilot (step 4)
- [ ] Retro after 2 weeks: what worked, what felt heavy, what to adjust (step 2)

Record all of this in your project's copy of [04-templates/project-profile.md](../04-templates/project-profile.md).

## Minimum viable adoption vs. full adoption

Minimum viable is step 0. Full is step 4.

| | Minimum viable | Full |
|---|---|---|
| Evidence or silence | Yes | Yes |
| Change card | Yes | Yes |
| Small, green commits | Yes | Yes |
| Risk-tiered review | Yes | Yes |
| Feature task documents | No | Yes |
| Benchmarked releases | No | Yes |
| Emergency lane, cadence rituals | No | Yes |

Start minimum viable if the team is new to this. Move to full adoption once the habits stick, usually after the pilot and its retro.

## Using AI agents (optional)

AI agents are optional helpers. They never own a decision gate: a human owner always does. Route work to the right kind of intelligence instead of using one large model for everything. If it's deterministic, it should be a script: same input hash should produce the same output.

| Kind of work | Route to |
|---|---|
| A fixed rule | A script |
| Static analysis | A pinned analysis tool |
| Interpretation against fixed rules | A small model |
| Technical reasoning | A medium model |
| Adversarial judgment or irreversible actions | A large model |
| High-impact decision | A human owner |

Every agent gets a narrow role, minimal tools, and a fixed brief. Use [04-templates/agent-brief.md](../04-templates/agent-brief.md): ROLE (the one thing this agent does), OBJECTIVE (what "done" looks like), INPUTS (exactly what it's given), CONSTRAINTS (what it must not do), OUTPUT schema (the structured shape of its answer), STOP condition (when it must stop and hand back), BUDGET (time, token and step limit), EVIDENCE (what proof it must attach).

Agents return structured output. They never decide gates: a human reads the output and decides.
