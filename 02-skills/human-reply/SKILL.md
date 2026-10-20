---
name: human-reply
description: Lints a reply to a person with output_lint.py (COM-01..20), cite_check.py (COM-19) and done_check before sending; chain human-review when judgment is pending. Use it on every reply that matters or leaves the session.
version: 1.0.0
triggers:
  - human reply
  - reply lint
  - before sending
  - output lint
  - verify citations
allowed-tools: [Read, mcp__metodo__reply_lint, mcp__metodo__done_check]
---

**IRON LAW**: the model writes, the script measures the form and checks the citations, the owner decides the exceptions. Nothing ships with `FAIL` except with `--allow COM-xx` and the reason written down; no `[Measured]` with a `MISSING` citation ever ships.

## Input

The reply in a markdown file (`round/NNN-reply.md` if there is a round; otherwise a temp file), its type (`pregunta | estado | decision | fallo | investigacion | aclaracion`), the human's language (`es | en | ca | de`), the audience (`public` for anything that might leave the session; `owner` only for the interlocutor declared in the user file) and, if it cites code, the repo path.

## Steps

1. Write the reply with the `07-communication/identidad.es.md` block (or `identity.en.md`) and its type's skeleton from `07-communication/templates.md`. With audience `owner` and personal language enabled, ask the person "is this going to anyone else?" before using it; if yes, or with no answer, write for `public`.
2. If the reply says done, green, committed or delivered: `mcp__metodo__done_check` with `reply_path` and `repo` (and `session_dir` when known), then paste its `flag_block` verbatim in the human layer, never trimmed or reworded (COM-20). A BLOCK line is fixed, or named under `Not tested:` and taken to the owner; only the owner waives (`03-tools/bin/done-waive.sh`).
3. `mcp__metodo__reply_lint` with `reply_path`, `type`, `lang`, `audience` and, if it cites code, `repo`; `online=true` only if the owner asks for it, and it gets declared. Returns `output_lint` and `cite_check` separately; if there is a round, save them as `<reply>.lint.json` and `<reply>.cites.json`.
4. On `FAIL` in either one: fix the reply and repeat steps 2-3. Two passes at most; on the third, either it gets downgraded with `allow=[COM-xx]` and the reason is written in the minutes or the message, or the owner is asked. A `MISSING` citation is never downgraded: fix the citation or lower the tag.
5. If the reply carries an analogy, a long list, a new technical term, or a number without a unit (the `proposed` rules), chain the `human-review` skill before sending.
6. Send the reply. If there is a round, both JSON files stay in `round/` with their number.

## What the model may add

The wording, the analogy, and the decision of what goes to the human layer and what to the technical layer. Never a verdict different from what the script printed, nor a `[Measured]` tag on something `cite_check.py` could not see (`UNVERIFIED` is declared with `[Inferred]` or with the URL in view).

## Output

The sent reply, `<reply>.lint.json` (`verdict`, `rules[]`, `tool_sha`, `config_sha`), and `<reply>.cites.json` (`refs[]`, `uncited_measured[]`, `tool_sha`). The round's minutes note the `WARN`s left standing and the `--allow`s used.

## Escalate to the owner

- `COM-18` at FAIL: there is something irreversible that lived only in the technical layer.
- A `MISSING` citation the model does not know how to fix (the file or the sha does not exist where the source says).
- A third pass still at `FAIL`: the rule or the reply is wrong, and that is the owner's call.
- Any `--allow`.
