---
name: review-comment
description: Writes a code review comment with a fixed shape - first pr_scope.py separates the diffs that belong to the PR from base-branch noise, then the change's context is read (card, statement, and callers), and the comment is ONE short paragraph with What happens / Why it happens / Impact / How to fix plus the proposal in the code's language; review_comment_lint.py validates it. Use it on every PR review, your own or someone else's.
version: 1.0.0
triggers:
  - review comment
  - code review comment
  - comment on the PR
  - review the diff
  - pr scope
allowed-tools: [Read, Grep, Write, mcp__metodo__pr_scope, mcp__metodo__review_comment_lint]
---

**IRON LAW**: only comment on what the PR really changed (`pr_scope.py` says so, not the web view), quote the statement and not the comment, and every comment is a paragraph with four parts and a proposal that compiles in the file's language. Without the four parts there is no comment; without a `PASS` from the lint it does not get published.

## Input

`<repo>`, the base branch (`--base develop`), the tip of the PR (`--head`, default `HEAD`), and if it exists, the PR's change card (`round/001-card.md` or the PR description).

## Steps

1. Scope: `mcp__metodo__pr_scope` with `base` and `head`; save the output as-is as `round/NNN-pr-scope.json`. Only `pr_files` get comments. `base_drift_files` never get comments (they belong to the base, not the author). `mixed_files` are read with `git diff <base>...<head> -- <file>` (three dots), never with the two-dot view.
2. Context of the change, before judging: the card (`Why`, `How far`, `Invariant`), the statement at `file:line`, and its callers (`grep`). A comment that discusses something the card leaves out of scope with a ticket does not get written: it is noted as a collateral finding.
3. Write the comment with this template, in English:

````markdown
`path/File.kt:52` @ <sha>
What happens: <the fact, one sentence>. Why it happens: <the cause in the statement, one sentence>. Impact: <the hierarchy property it puts at risk, one sentence>. How to fix: <the mechanism, one sentence>.

```kotlin
<the minimal proposal, that compiles, in the file's language>
```
````

   Caps: four parts in a single paragraph, 200 characters per part and 600 total (`config/review-comment.json`). No preamble, no filler, no em dash. If `Why it happens` is not known, write "not conclusive" and what it would take to find out; never invent the cause.
4. `mcp__metodo__review_comment_lint` with `comment_path` and `scope_path=round/NNN-pr-scope.json`. On `FAIL`, fix and repeat; two passes at most.
5. Publish the comment on the cited line. Several findings, several comments: one per statement, never one long one with everything.

## What the model may add

The diagnosis, the wording, and the proposal. Never a comment on a `base_drift_files` file, never a proposal in pseudocode or another language, never a rewrite of the whole file (that is a new card for the proposer).

## Output

The published comments, `round/NNN-pr-scope.json`, and a lint `.json` per comment (`verdict`, `rules[]` RC-01..RC-07, `tool_sha`, `config_sha`).

## Escalate to the owner

- A finding on a critical path (`config/project.json: money_paths`) or on a critical hierarchy property: the comment gets written anyway and an adversarial round is also opened.
- `mixed_files` with more than half the diff coming from the base: the PR needs a rebase before review.
- A proposal that requires changing a shared build file: no agent ever applies it.
