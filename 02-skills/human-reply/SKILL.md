---
name: human-reply
description: Runs a reply addressed to a person through output_lint.py (form, rules COM-01..18) and cite_check.py (that what is cited exists, COM-19) before sending it; with judgment pending, chain human-review. Use it on every reply that matters - status, decision, failure, investigation, PR, minutes - and on any text that leaves the session.
version: 1.0.0
triggers:
  - human reply
  - reply lint
  - before sending
  - output lint
  - verify citations
allowed-tools: [Read, mcp__metodo__reply_lint]
---

**IRON LAW**: the model writes, the script measures the form and checks the citations, the owner decides the exceptions. Nothing ships with `FAIL` except with `--allow COM-xx` and the reason written down; no `[Measured]` with a `MISSING` citation ever ships.

## Input

The reply in a markdown file (`round/NNN-reply.md` if there is a round; otherwise a temp file), its type (`pregunta | estado | decision | fallo | investigacion | aclaracion`), the human's language (`es | en | ca | de`), the audience (`public` for anything that might leave the session; `owner` only for the interlocutor declared in the user file) and, if it cites code, the repo path.

## Steps

1. Write the reply with the `07-communication/identidad.es.md` block (or `identity.en.md`) and its type's skeleton from `07-communication/templates.md`. With audience `owner` and personal language enabled, ask the person "is this going to anyone else?" before using it; if yes, or with no answer, write for `public`.
2. `mcp__metodo__reply_lint` with `reply_path`, `type`, `lang`, `audience` and, if it cites code, `repo`; `online=true` only if the owner asks for it, and it gets declared. Returns `output_lint` and `cite_check` separately; if there is a round, save them as `<reply>.lint.json` and `<reply>.cites.json`.
3. On `FAIL` in either one: fix the reply and repeat step 2. Two passes at most; on the third, either it gets downgraded with `allow=[COM-xx]` and the reason is written in the minutes or the message, or the owner is asked. A `MISSING` citation is never downgraded: fix the citation or lower the tag.
4. If the reply carries an analogy, a long list, a new technical term, or a number without a unit (the `proposed` rules), chain the `human-review` skill before sending.
5. Send the reply. If there is a round, both JSON files stay in `round/` with their number.

## What the model may add

The wording, the analogy, and the decision of what goes to the human layer and what to the technical layer. Never a verdict different from what the script printed, nor a `[Measured]` tag on something `cite_check.py` could not see (`UNVERIFIED` is declared with `[Inferred]` or with the URL in view).

## Output

The sent reply, `<reply>.lint.json` (`verdict`, `rules[]`, `tool_sha`, `config_sha`), and `<reply>.cites.json` (`refs[]`, `uncited_measured[]`, `tool_sha`). The round's minutes note the `WARN`s left standing and the `--allow`s used.

## Escalate to the owner

- `COM-18` at FAIL: there is something irreversible that lived only in the technical layer.
- A `MISSING` citation the model does not know how to fix (the file or the sha does not exist where the source says).
- A third pass still at `FAIL`: the rule or the reply is wrong, and that is the owner's call.
- Any `--allow`.
