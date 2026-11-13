# Position: where the kit stands

Most of the kit is what the market already ships. Three things in it were not found elsewhere in the survey. Its review method derives from Gentle AI. The leaders are ahead on distribution and team policy. This page claims no first.

To adopt the kit, read [07-adoption.md](07-adoption.md). To test it on your repo, read [09-measurement.md](09-measurement.md).

## How to read this page

Everything here comes from two research files in this repo. Nothing was fetched again for this page.

| Source | Date | What it is |
|---|---|---|
| `odd/research/benchmark-landscape/report.md` (the survey) | sources accessed 2026-10-20 | A comparison of the kit with about fifteen frameworks |
| `odd/research/kit-audit-2026-11/audit.md`, section 7 (the audit) | 2026-11-12 | A summary of market position. It says its market facts were not re-fetched and should be read as Inferred |

"Not found" means not found in the READMEs of the surveyed projects. Those projects were not audited, and the survey ran no dedicated search for these features. So "not found" is not "absent everywhere" [Inferred, as both sources state]. The notes the audit took its market facts from are not in this tree, so the audit is the last source you can open here.

## 1. Rare or unclaimed in the survey

| What the kit has | What the survey found elsewhere | In this tree | Tag |
|---|---|---|---|
| A tag on every claim, and a script that checks the cited file and line exist | Not found in any surveyed framework | `03-tools/lib/cite_check.py` | Inferred |
| Tests that prove its own scripts are deterministic, with negative controls | Gentle AI's bench is deterministic, but no tests asserting it were found | `03-tools/tests/` | Inferred |
| A benchmark of itself with a vanilla arm, an arm-validity gate and published "unsupported" verdicts | Gentle AI's README has one vendor run (n=1) and an offline bench. The survey calls the kit's "rare; the most complete instance found" | `08-benchmark/` | Inferred |

The audit adds one writing rule to this list: cite the statement, not the comment.

## 2. Already claimed by someone else

Gentle AI is credited here by name. The kit's review receipt (RDD) is an adaptation of Gentle AI's Receipt-Driven Development, and the kit's own rule file says so (`00-principles/review-receipt.md`) [Measured in this tree]. The survey reports the same origin for the kit's task documents (ODD) [Inferred].

| Mechanism | Who has it, per the survey | The kit's relation to it |
|---|---|---|
| Review receipts bound to a frozen candidate, and review sized by risk tier | Gentle AI's RDD only | A parallel implementation of Gentle AI's concept |
| Feature and spec documents | Spec Kit, Kiro, BMAD, Agent OS, Superpowers, Gentle AI | Adapted from Gentle AI |
| Blind dual judges with bounded rounds | Gentle AI's judgment-day only | The kit's in-loop judge is not blind. Its blind judge exists only in the benchmark |
| Dual adversarial review, and a published loss | Gentle AI (the audit) | Compare against Gentle AI; claim no novelty |

A repo that already runs Gentle AI can keep it in charge: the config key `rdd.review_authority` takes `kit` or `gentle-ai` (`03-tools/config/project.json`) [Measured].

## 3. Commodity

Everyone ships these. They are no reason to pick the kit [Inferred: both sources].

| Mechanism | Also shipped by |
|---|---|
| Spec before code, task lists, a rules file, review gates, a fast path for small work | Spec Kit, OpenSpec 2.0, BMAD V7 (the audit) |
| An instructions file and a context pack | `AGENTS.md`, used by more than 60,000 projects (the survey) |
| Blocking hooks | Claude Code and Kiro runtimes |
| A model and effort per subagent | Claude Code frontmatter, Amp modes, aider's architect mode |
| Persistent memory | Claude Code subagent memory, Devin, Bugbot, Engram |
| Multi-agent or adversarial review | Claude Code's `code-review` plugin, Codex adversarial review |

## 4. What the leaders do better

The audit's verdict on each row is one word: adopt.

| Area | Who leads, per the audit | Tag |
|---|---|---|
| Distribution through skill and plugin marketplaces | Claude Code's official marketplace (317 plugins); Spec Kit presets and private catalogs | Inferred |
| Team policy: managed settings and single sign-on | named as a leader practice, no project named | Inferred |
| Evaluations with and without a skill | Tessl | Inferred |
| A human-approval inbox for learned memory | Gemini CLI | Inferred |
| Adoption, in GitHub stars on 2026-11-12 | Superpowers 316.5k, Spec Kit 149.5k, OpenSpec 74.7k, BMAD 55.3k, Gentle AI 8.8k | Inferred |

## 5. What nobody has shown, the kit included

- **No surveyed framework has an independent controlled evaluation.** Spec Kit, BMAD, Superpowers and Agent OS publish no measurement of their own effect [Measured by the survey, accessed 2026-10-20].
- **The evidence that any of them improves outcomes is thin.** One vendor-run benchmark of 50 tickets shows 72% merged without specs against 80 to 84% with, inside a noise band of ±10 points. The one controlled study of instruction files found no gain and over 20% more cost [Inferred: the audit].
- **The kit has not finished its own proof.** Its comparison on file is one pull request. There its review found 7 valid findings against 6 for vanilla at 6.3 times the cost, and Claude Code's `code-review` skill found 8 at about a quarter of the kit's price (`08-benchmark/reports/pilot-pr176.md`) [Measured, n=1, the kit's own run].
- **The kit's own data does not support every part of it.** The survey reads that data as supporting the blocking gates and the two adversaries, and as not supporting the warn-only lints, the memory bridge, the router or the judge as a filter [Inferred by the survey from self-reported numbers].

The opening the audit sees is honest measurement: no surveyed framework ships outcome metrics, and it is also the part the kit has not finished [Inferred: the audit].
