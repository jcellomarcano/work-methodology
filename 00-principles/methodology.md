# Working methodology with agents · generic v3

The kit's operating law. Every rule exists because its absence cost something on a real project; cases
are cited as "real case" without naming the project. The long documents this law points to: `why-layer.md`,
`change-card.md`, `agent-protocol.md`, `model-routing.md`, `../06-languages/`. Cap: 250 lines,
validated by `03-tools/lib/docs_lint.py`.

## 0. The rule that governs the rest: evidence or silence

No claim enters a report, a PR, minutes, or a message without **file:line with the sha it was read at, a
commit sha, a log timestamp, or pasted command output**. If it can't be proven, say "inconclusive" and
write down what evidence is missing and how to get it. Every claim carries an epistemic tag:
**Measured · Tested · Inferred · Assumed · Unknown**. It never rises without new evidence; it **drops**
when its evidence dies (a test deleted or ignored, a line moved, a branch reverted).

Corollaries we paid for:
- **A generated file is not proof.** Real case: a `BuildConfig` said `false` while the binary ran with `true`.
- **A patch's fingerprint is not content.** To know whether something reached a branch, diff the trees, not the commits.
- **The log can lie.** An obfuscator merges empty classes and `simpleName` prints the survivor. Name the types from the type.
- **Silence is not a data point.** An instrument that can't see something DECLARES it (`TRUNCATED`), never emits empty.
- **A binary's identity is `git_sha` + `git_dirty`**, not its readable version.
- **An "improved" regex is tested against real data before it's claimed.**
- **Cite the statement, not the comment.** Real case: 5 of 6 agents called an imperative machine pure because its KDoc said "pure".

## 0-bis. The questions that govern

We do not optimize code: we optimize **system properties**. Each project declares its hierarchy of what's
protected in tie-break order (`config/project.json`); speed yields to the properties above it.
**Simplicity before over-engineering**: nothing is abstract or complex on principle; the simplest
solution that satisfies the invariants wins, and a new abstraction earns its cost only with a second real
reason to change. Before deciding how to implement something, six questions, written and tagged:
1. Why does this exist, and what problem are we really solving?
2. What must stay true? (the project's invariants, with their guarantee mechanism)
3. What do we protect and what do we risk? (one hierarchy property on each side)
4. Where does the truth live? (what evidence lets us claim a state, not which variable says so)
5. What do we assume and how do we know it?
6. Are we making the system simpler or just the code shorter? Is there a simpler solution meeting the same terms?

Checkable simplicity rules, each with its detector: **SIMP-1** copy the existing mold, no abstraction
shared by two cases until a third one needs it with the owner's decision (diff against the mold);
**SIMP-2** a new interface only if a test replaces it with a fake (grep `interface` vs `src/test`);
**SIMP-3** port, don't redesign: changing a behavior is a separate card (the origin's tests pass without
touching their assertions); **SIMP-4** code written from scratch is bounded per slice, and if it's
exceeded, `How far` explains it (`metrics.sh`); **SIMP-5** no new flags or configuration the fleet doesn't
need today; **SIMP-6** `How far` lists what is NOT being built; **SIMP-7** the challenger writes
`simpler_alternative` in every finding; **SIMP-8** cleverness isn't commented, it's renamed or extracted
(DOC-001).

**Every defense of a change is a nine-field card** (`change-card.md`). Same shape always; only the
content changes. No card, no PR. The card also declares the change's budget (agents and tokens).

## 1. Cartographer before surgery

Before touching non-trivial code, a cartographer builds the map: what exists, what gets reused, what's
obsolete, what conflicts will arise (`merge-tree`). No map, no conflict gets resolved. Real case: a map
avoided an 18-commit redundant rebase; another avoided rewriting a branch that already existed. The map
comes from the `cartography` skill (deterministic script + a medium model's reading), with a fixed output
schema, and is reused if it's under a week old.

## 2. Every commit green on its own (gstack)

One commit, one idea, and the project's battery passes **on that commit**, not just at the end of the
branch (skill `verify-per-commit`); the full battery per branch before pushing. A commit that isn't green
on its own doesn't enter the stack. A push with `--no-verify` is declared in the PR, under "what was NOT
tested"; staying silent about it invalidates the claim "battery green".

## 3. Round of the two adversaries, and it comes before the push

Two roles, always: the **challenger** attacks what the design claims with a declared lens and gives OK /
NUANCE / BROKEN; the **blind-spot adversary** looks for what nobody's watching (the absent case, the
ownerless assumption) and gives CLOSED / OPEN WITH OWNER / CONTAINED. **A BROKEN gets fixed before
pushing; an OPEN needs an owner or a ticket.** If the challenger says OK and the blind-spot adversary says
OPEN on the same point, OPEN wins until a judge rules or the owner closes it; the orchestrator never
picks who to believe without writing it down.

Mandatory lenses: **simplicity** (is there a simpler solution that meets the same terms?), **critical
flow** (can something irreversible be lost, duplicated, or left ownerless? is it idempotent if the
process dies? does it block the real operation?), and **"never worse than before"** at startup, in the
real environment, and on critical paths. Adversaries go to the large model when `For what` **or**
`What it risks` is one of the project's critical properties, **or when the diff touches the declared
critical paths** in `config/project.json`, whatever the card says: the path outranks the declaration. The
facts they attack with come from scripts; if none exist, from a reading declared as such in the minutes.
Real case: an adversary knocked down a fix that was a no-op in 26 of 27 cases and harmful in the 27th.

**Depth by risk (receipt)**: exempt (docs only), low (scripts only), medium (one challenger on the medium
model with one lens and the sector battery), high (two large adversaries, a judge, and the full battery,
with prior consent). The layer is set by `rdd_risk.py` when the receipt opens and stays frozen with the
tree; detail in `review-receipt.md`.

## 4. The owner decides, and there are explicit gates

Stop and ask at: every real-environment deployment or restart, opening PRs, pushing, merging into
integration or release branches, changing a release's composition, touching the project's shared build
files (listed in `config/project.json`), creating external tickets, and any action that changes shared
state. **If an instruction rests on a premise that turns out false and was supplied by the agent, stop
and correct it before executing.** Executing a decision to the letter when it's based on the agent's own
wrong data isn't obedience, it's negligence. When planning: at least four rounds of questions to the
owner and, at the end, always ask whether they want more questions or to start. Pending per project: an
emergency lane (what gets compressed in an urgent fix and who signs off) and what an agent does when the
owner isn't available.

## 5. Code rules

The source is the project's committed conventions file (`CONVENTIONS.md`) and its per-language digest
(`../06-languages/`). Rules carry a stable ID and a declared detector (`active · silenced · proposed`).
- **Modeled data, pure decisions, effects at the edge.** States and results as closed types; critical-flow
  transformations as small pure functions in their own file, testable without a framework or a device. In
  critical flow **auditability** rules: every row's destination reads at a glance.
- **Fewer lines WITH more resolutions**, never fewer lines through unreadable compression.
- **DRY of knowledge, not of keystrokes.** Extract when the business rule is the same, not when the text
  matches. Before writing, search whether it's already solved in the repo.
- **New code follows the style; old code only under its own ticket.** No opportunistic rewrites.
- **DOC-001, the code explains itself.** The proposer doesn't write comments: it leaves
  `NEEDS-COMMENT: <reason>`; `comment_gate.py` measures, `generic-comment-gate` judges against ISO
  24495-code v0.6.2 (a comment says why, interface documentation says what the caller needs), the
  mechanic applies it, and `--verify` closes the round.
- **Third-party SDK rule**: a vendor defect is **reported with evidence**; an unavoidable patch is born
  tagged with its retirement condition. An SDK bump touches shared build files: a person does it under
  their own protocol, never an agent.

### Tests (anti-flake doctrine, paid for in CI incidents)

- **A test waits for exactly the condition it asserts.** Waiting for A and reading B is the root of
  nearly every flake; fix it in the expected condition, never with sleeps or retries.
- **Wait WHERE you read.** A component having seen an event doesn't prove the file has it.
- **A test never asserts who won a legitimate race**: it asserts the invariant, accepting either winner.
- **The fixture mimics the REAL shape of production.** A stale fixture is a test that lies.
- **Negative control, always.** A guard that can't fail protects nothing: force the red once.
- Locally "it doesn't fail" almost never means "it can't fail": it means a small race window.

## 6. Git

- Merge commit **only between integration and release branches**, both directions. Everything else,
  rebase and fast-forward. The merge button is chosen by hand: real case, a rebase where a merge was
  needed duplicated ~150 commits and left the release branch without the subject the train pulls its
  notes from. Squash, same deal.
- Backups as **tags** before destroying anything. `--force-with-lease`, never `--force`.
- No AI attribution in commits. Outside commits: local agent configuration, audit documents, and
  secrets. Registered exception per project: a local branch that keeps the agents and skills so they can
  be pushed someday; the kit is the source, the copies are generated by script and not hand-edited.
- Messages in the repo's language and style, explaining **why**, not what.

## 7. The release train

- Release notes come from the release PR's description: the human summary in customer language, and
  the internal part (card, benchmark, mechanics) inside `<!-- -->`, under whatever character cap the
  train imposes.
- The tag pipeline fires only on the tag push; relaunching means re-emitting the same tag, byte for byte.
- Deployment environments and credentials are validated before the first cut; a missing credential
  degrades with a warning, never silently and never in green.
- **No merge to the release branch without a benchmark in the PR** (skill `benchmark-release`): what
  improves, what worsens, why (from the cards), how, what it does, **what was NOT measured**. Base: the
  last shipped tag; candidate: the PR's sha; never the tip of the release branch. Plus a weekly snapshot
  of the integration branch for the trend.
- Version readers are tested against every shape of the build file before being claimed correct.

## 8. Measurement in a real environment (device, test bench, staging)

- **One primary metric per arm**, declared with its success criterion BEFORE running; **single-variable
  arms**; **medians**, not one sample; **negative control** whenever one exists; **observer effect**
  declared; simulations or doubles declared (a median with simulation is not Measured).
- Verify the instrument works **before** measuring. Bench and diagnostic builds without cache.
- A real environment is held by one session at a time, and who holds it is written on the board.
- When reading field logs, "new behaviors" are sometimes **old behaviors uncovered**: ask what changed
  in the FLOW before hunting the bug. The minutes come from the `real-environment-minutes` skill.

## 9. Routing by kind of intelligence

The question isn't "which model is cheap" but "what kind of intelligence does this task need?". Table,
budgets, and orchestration in `model-routing.md`. Summary: rule → script; AST → pinned tool;
interpretation against a fixed rulebook → small model; technical reasoning → medium model; adversarial
judgment or critical flow → large model; high impact → owner. Never a general-purpose agent: each role is
an agent with `model`, minimal `tools`, and a JSON contract. A medium model orchestrates the routine
work; the highest-judgment one designs, decides, and talks to the owner. Inter-agent communication:
`agent-protocol.md`.

## 10. Deliverables

**Real-environment minutes**: arm, metric, criterion, result with pasted evidence, arms discarded and
why. **PR messages** (skill `pr-message`): what it fixes, evidence, card, "what was NOT tested".
**Bug reports**: the symptom as the customer sees it, the cause with measurements, "what this bug is
NOT". **Collateral findings**: noted with a ticket, not fixed in passing. **Every change leaves future
context**: code, test, invariant, decision, evidence, metric, explicit limit.

## 11. Communication

Fixed project vocabulary (one word per concept). Results are reported **as they are**: if something
fails, show the output; if a step was skipped, say so; if an earlier claim was false, correct it head on.
Your own mistakes are counted the same as anyone else's.

## 12. Determinism and cost

- **Everything that can be a script is a script.** Input: repo path + sha. Output: JSON with ordered
  keys, no timestamps or absolute paths, with `tool_versions`, `tool_sha`, `repo_sha`, and `repo_dirty`;
  baseline per sha and delta between runs. Same repo, same sha, same output, or the script is broken. A
  delta between two different `tool_sha`s is void; a dirty tree produces no baseline; thresholds live in
  config and changing them is a change with a card.
- **Skills wrap scripts**; the model interprets, never re-derives numbers. Every script ships with a
  negative control and a determinism test. Whatever needs a build or a real environment is declared in
  `not_measured`.
- **Context hygiene**: compact when closing each block, clean up when switching tasks, no agent starts
  above its cap; the session log measures tokens per phase and per agent. Large assignments get split
  into units with their own stop: real case, an implementation train consumed nine times its cap.
- **Ratchet** (nothing worsens versus the baseline) only once the metrics have proven stable, warn-only
  first, with the owner's OK and a signed override written in the PR; critical flow stays exempt from the
  heuristic ratchet until the detector is AST-based.
- **Whatever the harness can apply, the harness applies, the model doesn't have to remember it.** Gates,
  budget, and output shape are enforced with deterministic hooks (`03-tools/hooks/`); scripts are called
  as typed tools (the `metodo` MCP server). A receipt is tied to the tree (`HEAD^{tree}`), never to the
  commit: same tree, same receipt.
