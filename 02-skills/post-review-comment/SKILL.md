---
name: post-review-comment
description: Publishes a linted review comment on a PR in the form the author actually reads, one bullet per tag, through review_comment_post.py. The paragraph form is only review_comment_lint's input; this skill renders it and posts it, dry-run first. Use it right after review-comment gets a lint PASS, never before.
version: 1.0.0
triggers:
  - publish the comment
  - post the review comment
  - post to bitbucket
  - update the pr comment
allowed-tools: [Read, Bash]
---

**IRON LAW**: only a comment with a lint `PASS` is posted; the posted form is one bullet per tag; posting is outward-facing, so the owner asks for it and sees the dry run first.

## Input

`<comment.md>` (the paragraph comment, already `PASS` from `review_comment_lint`), the PR's `--repo WORKSPACE/REPO` and `--pr N`, and, when editing an already-posted comment, its `--comment-id`.

The script lives in the kit's tools root: `POST="${METODO_TOOLS:-__TOOLS_DEFAULT__}/lib/review_comment_post.py"` (the installer renders the default; `METODO_TOOLS` overrides it).

## Steps

1. Lint: the comment already carries a `PASS`. A comment with any `FAIL` never reaches this skill.
2. Render: `python3 "$POST" render <comment.md>` turns the paragraph into one bullet per tag; the anchor line and the snippet stay unchanged.
3. Dry run: `python3 "$POST" post <comment.md> --repo <repo> --pr <n>` without `--confirm` prints the exact method (`POST`/`PUT`), url, and payload, and sends nothing. Show it to the owner before sending.
4. Post: only after the owner's go-ahead, repeat the same command with `--confirm --ledger round/NNN-comments-posted.json`. On success it prints the posted or updated comment's id.
5. Edit, never duplicate: an already-posted comment that needs a change is updated with `--comment-id <id>` (`PUT`), never a second comment on the same finding.

## What the model may add

Nothing: rendering and posting are both mechanical. What it may not add: a comment that has not passed the lint, a second comment for an already-posted finding, or `--confirm` without having shown the dry run first.

## Output

The dry-run JSON shown to the owner, the posted or updated comment's id, and the ledger entry.

## Escalate to the owner

- The dry-run payload looks wrong (wrong file, wrong line, wrong PR): stop before `--confirm`.
- The Bitbucket API answers with anything other than 2xx: check the token, the PR number, and the comment id before retrying.
- Editing a comment the owner did not ask to edit: never overwrite silently.
