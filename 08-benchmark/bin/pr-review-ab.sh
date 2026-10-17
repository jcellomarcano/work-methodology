#!/usr/bin/env bash
# PR review A/B runner for Claude Code (non-interactive `claude -p`).
#
# Reviews one PR twice with the same model, effort and prompt: arm `kit`
# (hooks, skills and MCP as installed) and arm `vanilla` (kit hooks silenced
# through METODO_TOOLS=/nonexistent, skills and MCP servers disabled). Then a
# blind judge in an empty directory rates both reviews under coin-flipped
# labels. Everything lands under 08-benchmark/data/ab/<pr-id>/ (gitignored).
#
# usage: pr-review-ab.sh <repo> <pr-id> <head-ref> <model> [effort] [base-branch]
#   repo         path to the checkout that holds the PR branch
#   pr-id        a label for the files, e.g. 283
#   head-ref     the PR head (branch name or sha); the sha is pinned for both arms
#   model        e.g. claude-opus-5-5 (same for both arms and the judge)
#   effort       low|medium|high|xhigh|max (default high)
#   base-branch  the PR destination, e.g. origin/develop (default: the remote HEAD branch)
#
# env AB_ARM_PROMPT     template for the kit arm instead of protocols/prompts/arm.txt, e.g.
#                       to run a review skill; <CONTRACT> in it becomes arm.txt, so the judge
#                       still scores the same JSON shape. The vanilla arm always uses arm.txt.
# env AB_REUSE_VANILLA  a previous run dir for the same diff: its vanilla arm is copied, not re-run.
# env AB_ARM_EVIDENCE   rg pattern that the non-vanilla arm's transcript must match to count as
#                       having run what its prompt asked for (default: kit evidence). Comparators
#                       such as arm-code-review.txt set their own, e.g. '"skill":"code-review"'.
#
# Needs: claude >= 2.1 on PATH, git, python3. Set CLAUDE_BIN to use another
# binary (the test suite points it at a stub).
set -euo pipefail

if [ $# -lt 4 ]; then
  sed -n '2,20p' "$0" >&2
  exit 2
fi

REPO="$(cd "$1" && pwd)"; PR_ID="$2"; HEAD_REF="$3"; MODEL="$4"; EFFORT="${5:-high}"
CLAUDE="${CLAUDE_BIN:-claude}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${AB_OUT_DIR:-$HERE/data/ab}/$PR_ID"
RUNS="${AB_RUNS_FILE:-$HERE/data/ab-runs.jsonl}"
mkdir -p "$OUT" "$(dirname "$RUNS")"

SHA="$(git -C "$REPO" rev-parse --verify "$HEAD_REF^{commit}")"
# Both arms read the working tree, so it must be the PR head, clean. Refuse otherwise.
if [ "$(git -C "$REPO" rev-parse HEAD)" != "$SHA" ]; then
  echo "refusing: $REPO is not checked out at $SHA. Run: git -C $REPO switch --detach ${SHA:0:12}" >&2
  exit 4
fi
if [ -n "$(git -C "$REPO" status --porcelain --untracked-files=no)" ]; then
  echo "refusing: $REPO has uncommitted tracked changes; stash or commit them first" >&2
  exit 4
fi
BASE_BRANCH="${6:-$(git -C "$REPO" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)}"
BASE_BRANCH="${BASE_BRANCH:-main}"
BASE="$(git -C "$REPO" merge-base "$BASE_BRANCH" "$SHA")"
git -C "$REPO" diff "$BASE...$SHA" > "$OUT/diff.patch"
ARM_TXT="$HERE/protocols/prompts/arm.txt"
KIT_PROMPT="${AB_ARM_PROMPT:-$ARM_TXT}"
REUSE="${AB_REUSE_VANILLA:-}"
if [ -n "$REUSE" ] && ! cmp -s "$REUSE/diff.patch" "$OUT/diff.patch"; then
  echo "refusing: $REUSE reviewed a different diff; its vanilla arm is not a baseline for $SHA" >&2
  exit 4
fi

# Same allowlist in both arms: read-only inspection, git history, the project's test
# runner, delegation, and the kit's MCP tools (absent in vanilla). No free shell.
ALLOWED='Read,Grep,Glob,Agent,Skill,Bash(git diff:*),Bash(git show:*),Bash(git log:*),Bash(./gradlew:*),mcp__metodo__*'

build_prompt() {  # $1 template, then VAR=value pairs replace <VAR>
  python3 -I - "$@" <<'PY'
import pathlib, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
for pair in sys.argv[2:]:
    key, _, value = pair.partition("=")
    if value.startswith("@"):
        value = pathlib.Path(value[1:]).read_text(encoding="utf-8")
    text = text.replace(f"<{key}>", value)
sys.stdout.write(text)
PY
}

extract() {  # $1 raw json from claude -p, $2 destination for the review json, prints summary line
  python3 -I - "$1" "$2" <<'PY'
import json, pathlib, re, sys
raw = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
result = raw.get("result") or ""
m = re.search(r"```json\s*(.*?)```", result, re.S)
block = m.group(1).strip() if m else None
findings = None
if block:
    try:
        findings = json.loads(block)
    except json.JSONDecodeError:
        findings = None
pathlib.Path(sys.argv[2]).write_text(json.dumps(findings, indent=1, sort_keys=True) + "\n" if findings is not None else "null\n")
verdict = re.search(r"VERDICT:\s*(approve|request-changes)", result)
u = raw.get("usage") or {}
status = "ok" if findings is not None and not raw.get("is_error") else "failed"
summary = {
    "status": status,
    "session_id": raw.get("session_id"),
    "cost_usd": raw.get("total_cost_usd"),
    "duration_ms": raw.get("duration_ms"),
    "duration_api_ms": raw.get("duration_api_ms"),
    "num_turns": raw.get("num_turns"),
    "is_error": raw.get("is_error"),
    "input_tokens": u.get("input_tokens"),
    "cache_read": u.get("cache_read_input_tokens"),
    "cache_write": u.get("cache_creation_input_tokens"),
    "output_tokens": u.get("output_tokens"),
    "findings": len(findings) if isinstance(findings, list) else None,
    "verdict": verdict.group(1) if verdict else None,
}
print(json.dumps(summary, sort_keys=True))
PY
}

run_arm() {  # $1 arm name
  local arm="$1" prompt tpl="$ARM_TXT"
  [ "$arm" = "kit" ] && tpl="$KIT_PROMPT"
  if [ "$arm" = "vanilla" ] && [ -n "$REUSE" ]; then
    echo "== arm vanilla reused from $REUSE ==" >&2
    for f in raw.json review.json summary.json; do cp "$REUSE/vanilla.$f" "$OUT/vanilla.$f"; done
    return
  fi
  # <CONTRACT> goes first so the placeholders inside arm.txt are filled too.
  prompt="$(build_prompt "$tpl" "CONTRACT=@$ARM_TXT" "PR=$PR_ID" "SHA=$SHA" "BASE=$BASE")"
  echo "== arm $arm (model $MODEL, effort $EFFORT, sha ${SHA:0:12}) ==" >&2
  local -a flags=(-p --model "$MODEL" --effort "$EFFORT" --output-format json
                  --allowedTools "$ALLOWED" --permission-prompts none --max-turns 80)
  if [ "$arm" = "vanilla" ]; then
    ( cd "$REPO" && METODO_TOOLS=/nonexistent "$CLAUDE" "${flags[@]}" --disable-slash-commands --strict-mcp-config "$prompt" ) > "$OUT/$arm.raw.json"
  else
    ( cd "$REPO" && "$CLAUDE" "${flags[@]}" "$prompt" ) > "$OUT/$arm.raw.json"
  fi
  local summary
  summary="$(extract "$OUT/$arm.raw.json" "$OUT/$arm.review.json")"
  echo "$summary" > "$OUT/$arm.summary.json"
  python3 -I -c '
import json, sys
s = json.loads(sys.argv[1]); s.update({"pr": sys.argv[2], "sha": sys.argv[3], "base": sys.argv[4], "model": sys.argv[5], "effort": sys.argv[6], "arm": sys.argv[7], "prompt": sys.argv[8]})
print(json.dumps(s, sort_keys=True))' "$summary" "$PR_ID" "$SHA" "$BASE" "$MODEL" "$EFFORT" "$arm" "$(basename "$tpl")" >> "$RUNS"
  echo "$summary" >&2
}

# Coin flip 1: which arm runs first (order effects are recorded, not assumed away).
if [ $((RANDOM % 2)) -eq 0 ]; then ORDER="kit vanilla"; else ORDER="vanilla kit"; fi
for arm in $ORDER; do run_arm "$arm"; done

# A failed arm (no findings block or an API error) never reaches the judge: the cell is marked failed (S9).
for arm in kit vanilla; do
  if [ "$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$OUT/$arm.summary.json")" != "ok" ]; then
    echo "arm $arm failed: no findings block or API error; judge not run. See $OUT/$arm.raw.json" >&2
    printf '{"status": "failed", "failed_arm": "%s"}\n' "$arm" > "$OUT/judge.summary.json"
    exit 3
  fi
done

# The kit arm must have run the kit (PR 176 lesson): its transcript needs a generic-* subagent,
# a kit skill or a mcp__metodo__* call. Without that evidence the cell is invalid, not scored.
KIT_SID="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["session_id"])' "$OUT/kit.summary.json")"
TRANSCRIPT="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}/$(printf '%s' "$REPO" | sed 's#/#-#g')/$KIT_SID.jsonl"
# Skill names: the English ones, then the pre-port Spanish ones older transcripts carry.
KIT_EVIDENCE='subagent_type":"generic-|"name":"mcp__metodo__|"name":"Skill","input":\{"skill":"(receipt-review|adversarial-round|review-comment|cartography|verify-per-commit|revision-con-recibo|ronda-adversarial-dos|comentario-de-review|cartografia|verify-por-commit)"'
EVIDENCE="${AB_ARM_EVIDENCE:-$KIT_EVIDENCE}"
if [ -f "$TRANSCRIPT" ]; then
  KIT_HITS="$(rg -c -e "$EVIDENCE" "$TRANSCRIPT" || true)"
  KIT_HITS="${KIT_HITS:-0}"
  python3 -I - "$OUT/kit.summary.json" "$KIT_HITS" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1]); s = json.loads(p.read_text()); s["kit_evidence_hits"] = int(sys.argv[2])
p.write_text(json.dumps(s, sort_keys=True) + "\n")
PY
  if [ "$KIT_HITS" -eq 0 ]; then
    echo "arm kit invalid: its transcript does not match the evidence pattern ($EVIDENCE); judge not run. Use AB_ARM_PROMPT=protocols/prompts/arm-kit-review.txt, or AB_ARM_EVIDENCE for a comparator" >&2
    printf '{"status": "invalid-arm", "failed_arm": "kit"}\n' > "$OUT/judge.summary.json"
    exit 5
  fi
else
  echo "warning: kit transcript not found at $TRANSCRIPT; kit evidence unverified" >&2
fi

# Blinding: tool names and kit/hook markers quoted inside a finding would tell the judge which
# arm it reads. They are redacted in the copy the judge sees; the stored reviews stay intact.
redact() {
  python3 -I - "$1" <<'PY'
import pathlib, re, sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
text = re.sub(r"mcp__[A-Za-z0-9_]+", "[tool]", text)
text = re.sub(r"(?i)\[metodo\]|metodo-hook|metodo mcp|gentle-ai|engram|judgment[- ]day|generic-(judge|adversar\w*|blind-spot-adversary|challenger|confrontador|proposer|mechanic|verifier|verificador|cartographer)", "[redacted]", text)
sys.stdout.write(text)
PY
}
redact "$OUT/kit.review.json" > "$OUT/kit.review.blind.json"
redact "$OUT/vanilla.review.json" > "$OUT/vanilla.review.blind.json"

# Coin flip 2: blind labels for the judge.
if [ $((RANDOM % 2)) -eq 0 ]; then A=kit; B=vanilla; else A=vanilla; B=kit; fi
printf '{"A": "%s", "B": "%s", "run_order": "%s"}\n' "$A" "$B" "$ORDER" > "$OUT/judge.mapping.json"
JUDGE_PROMPT="$(build_prompt "$HERE/protocols/prompts/judge.txt" "DIFF=@$OUT/diff.patch" "REVIEW_A=@$OUT/$A.review.blind.json" "REVIEW_B=@$OUT/$B.review.blind.json")"
JUDGE_DIR="$(mktemp -d)"
echo "== judge (blind, empty dir) ==" >&2
( cd "$JUDGE_DIR" && METODO_TOOLS=/nonexistent "$CLAUDE" -p --model "$MODEL" --effort "$EFFORT" --output-format json \
    --disable-slash-commands --strict-mcp-config --permission-prompts none --max-turns 3 "$JUDGE_PROMPT" ) > "$OUT/judge.raw.json"
rm -rf "$JUDGE_DIR"
extract "$OUT/judge.raw.json" "$OUT/judge.json" > "$OUT/judge.summary.json"

python3 -I - "$OUT" <<'PY'
import json, pathlib, sys
out = pathlib.Path(sys.argv[1])
mapping = json.loads((out / "judge.mapping.json").read_text())
judge = json.loads((out / "judge.json").read_text()) or {}
print("\n== result ==")
for arm in ("kit", "vanilla"):
    s = json.loads((out / f"{arm}.summary.json").read_text())
    letter = "A" if mapping["A"] == arm else "B"
    j = judge.get(letter) or {}
    print(f"{arm:8s} status={s['status']} findings={s['findings']} verdict={s['verdict']} cost=${s['cost_usd']} "
          f"turns={s['num_turns']} out_tokens={s['output_tokens']} cache_read={s['cache_read']} "
          f"| judge: valid={j.get('valid')} invalid={j.get('invalid')} unverifiable={j.get('unverifiable')}")
pref = judge.get("preferred")
print("preferred:", mapping.get(pref, "none") if pref else "none", "|", judge.get("preferred_why", ""))
print("missed by both:", len(judge.get("missed_by_both") or []))
print("files:", out)
PY
