#!/usr/bin/env bash
# Runs tools/verify/verify.sh (or --full) from <repo> against each commit of
# <range>, oldest to newest, each in a disposable worktree under
# out/worktrees/. <range> follows the normal semantics of `git log A..B`:
# excludes A, includes up to B: to verify only the new commits of a branch
# against develop, the typical usage is 'origin/develop..HEAD'.
#
# Serialized with out/.gradle.lock (lib/worktree.sh): two runs of this
# script, or one of this and one of bin/benchmark-release.sh, must not
# launch Gradle over the same repo at the same time.
#
# WARNING: this invokes Gradle once per commit (~4 min each with --full).
# Don't run it against a large range without reason.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <repo> <range> [--full]" >&2
  exit 2
fi

REPO="$(cd "$1" && pwd)"
RANGE="$2"
VERIFY_FLAG="${3:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/worktree.sh
source "$TOOLS_ROOT/lib/worktree.sh"

LOCK_DIR="$TOOLS_ROOT/out/.gradle.lock"
OUT_VERIFY_DIR="$TOOLS_ROOT/out/verify"
WORKTREES_DIR="$TOOLS_ROOT/out/worktrees"
mkdir -p "$OUT_VERIFY_DIR" "$WORKTREES_DIR"

VERIFY_ARGS=()
if [ "$VERIFY_FLAG" = "--full" ]; then
  VERIFY_ARGS+=("--full")
fi

# oldest-first: `git log` gives newest-first by default, --reverse flips it.
mapfile -t COMMITS < <(git -C "$REPO" log --reverse --format='%H' "$RANGE")

if [ "${#COMMITS[@]}" -eq 0 ]; then
  echo "ERROR: range '$RANGE' has no commits (A and B swapped? already all merged?)" >&2
  exit 2
fi

RESULTS_JSONL="$(mktemp)"
trap 'rm -f "$RESULTS_JSONL"' EXIT

for SHA in "${COMMITS[@]}"; do
  SUBJECT="$(git -C "$REPO" log -1 --format='%s' "$SHA")"
  WORKTREE_DIR="$WORKTREES_DIR/verify-commit-$SHA"
  LOG_PATH="$OUT_VERIFY_DIR/$SHA.log"
  LOG_REL="out/verify/$SHA.log"

  worktree_lock_acquire "$LOCK_DIR"
  worktree_add "$REPO" "$SHA" "$WORKTREE_DIR"

  VERDICT="PASS"
  if [ -x "$WORKTREE_DIR/tools/verify/verify.sh" ]; then
    if ! (cd "$WORKTREE_DIR" && "./tools/verify/verify.sh" "${VERIFY_ARGS[@]}") > "$LOG_PATH" 2>&1; then
      VERDICT="FAIL"
    fi
  else
    echo "ERROR: $SHA has no executable tools/verify/verify.sh" > "$LOG_PATH"
    VERDICT="FAIL"
  fi

  worktree_remove "$REPO" "$WORKTREE_DIR"
  worktree_lock_release "$LOCK_DIR"

  echo "-- $SHA ($VERDICT): $SUBJECT" >&2

  python3 -c "
import json, sys
print(json.dumps({'sha': sys.argv[1], 'subject': sys.argv[2], 'verdict': sys.argv[3], 'log': sys.argv[4]}))
" "$SHA" "$SUBJECT" "$VERDICT" "$LOG_REL" >> "$RESULTS_JSONL"
done

RANGE_SANITIZED="$(printf '%s' "$RANGE" | tr '/: ' '___' | tr -cd '[:alnum:]_.-')"
# The name also carries the repo's tip: two different worktrees can use the
# same range ('55529c347..HEAD' is valid for slice 2 and for its fix) and,
# without this suffix, the second run silently overwrote the first one's
# result. Measured on 15-sep: one slice's evidence got replaced by another's.
HEAD_SHORT="$(git -C "$REPO" rev-parse --short=9 HEAD)"
OUT_JSON="$OUT_VERIFY_DIR/$RANGE_SANITIZED.$HEAD_SHORT.json"

python3 -c "
import json
import sys
sys.path.insert(0, '$TOOLS_ROOT')
from lib import baseline, toolenv

commits = []
with open('$RESULTS_JSONL', encoding='utf-8') as fh:
    for line in fh:
        line = line.strip()
        if line:
            commits.append(json.loads(line))

repo_sha = commits[-1]['sha'] if commits else baseline.git_head_sha('$REPO')
repo_dirty = baseline.is_repo_dirty('$REPO')
versions = toolenv.tool_versions('$TOOLS_ROOT')
payload = baseline.base_envelope('$TOOLS_ROOT', repo_sha, versions, repo_dirty)
payload.update({'range': '$RANGE', 'commits': commits})
baseline.write_json('$OUT_JSON', payload)
"

echo "" >&2
echo "output at: $OUT_JSON" >&2
FAIL_COUNT=$(grep -c '"verdict": "FAIL"' "$OUT_JSON" || true)
if [ "$FAIL_COUNT" -gt 0 ]; then
  echo "$FAIL_COUNT commit(s) FAILED" >&2
  exit 1
fi
exit 0
