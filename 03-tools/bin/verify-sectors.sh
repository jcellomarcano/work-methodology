#!/usr/bin/env bash
# Runs only the Gradle tasks of the modules the change touches, per
# lib/test_sectors.py, with the same discipline as the repo's
# tools/verify/verify.sh: one gradlew invocation per task, one log per task,
# and everything under the out/.gradle.lock lock (lib/worktree.sh) so that
# two Gradle runs never overlap on the same repo. This is the agent loop's
# battery; the full one is still owned by pre-push and CI.
#
#   bin/verify-sectors.sh <repo> [--base REF] [--tasks a,b] [--committed-only] [--run-id ID] [--config project.json]
#
# Exit: 0 all green; 1 some task failed; 2 usage, lock, or gradlew missing;
# 3 full_required (nothing runs: the full battery is needed).
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <repo> [--base REF] [--tasks a,b] [--committed-only] [--run-id ID] [--config project.json]" >&2
  exit 2
fi

REPO="$(cd "$1" && pwd)"; shift
BASE=""; TASKS_ARG=""; COMMITTED_ONLY=""; RUN_ID=""; CONFIG_ARG=()
while [ $# -gt 0 ]; do
  case "$1" in
    --base) BASE="$2"; shift 2;;
    --tasks) TASKS_ARG="$2"; shift 2;;
    --committed-only) COMMITTED_ONLY="--committed-only"; shift;;
    --run-id) RUN_ID="$2"; shift 2;;
    --config) CONFIG_ARG=(--config "$2"); shift 2;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib/worktree.sh
source "$TOOLS_ROOT/lib/worktree.sh"

REPO_SHA="$(git -C "$REPO" rev-parse HEAD)"
DIRTY_SUFFIX=""
if [ -n "$(git -C "$REPO" status --porcelain | grep -v '\.claude/' || true)" ]; then DIRTY_SUFFIX="-dirty"; fi
RUN_ID="${RUN_ID:-$(date +%Y%m%d%H%M%S)-$$}"
RUN_DIR="$TOOLS_ROOT/out/verify-sectors/$REPO_SHA$DIRTY_SUFFIX/$RUN_ID"
mkdir -p "$RUN_DIR"

BASE_ARGS=()
[ -n "$BASE" ] && BASE_ARGS=(--base "$BASE")
python3 "$TOOLS_ROOT/lib/test_sectors.py" "$REPO" "${BASE_ARGS[@]}" $COMMITTED_ONLY "${CONFIG_ARG[@]}" > "$RUN_DIR/selection.json"

FULL_REQUIRED="$(python3 -c "import json,sys; print(str(json.load(open(sys.argv[1]))['full_required']).lower())" "$RUN_DIR/selection.json")"
if [ -z "$TASKS_ARG" ] && [ "$FULL_REQUIRED" = "true" ]; then
  echo "full_required: the change touches shared build files, binaries, or sectorless paths; run the full battery" >&2
  python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(json.dumps(d['full_required_reasons'], indent=2))" "$RUN_DIR/selection.json" >&2
  exit 3
fi

if [ -n "$TASKS_ARG" ]; then
  IFS=',' read -r -a TASKS <<< "$TASKS_ARG"
else
  mapfile -t TASKS < <(python3 -c "import json,sys; [print(t) for t in json.load(open(sys.argv[1]))['tasks']]" "$RUN_DIR/selection.json")
fi

# Credential gate (e.g. an SDK download key): without it, the tasks that
# need it are skipped and listed; the value is never read or printed.
SKIPPED=()
GATE_JSON="$(python3 -c "import json,sys; g=json.load(open(sys.argv[1])).get('credential_gate') or {}; print(json.dumps(g))" "$RUN_DIR/selection.json")"
if [ "$GATE_JSON" != "{}" ]; then
  GATE_KEY="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('local_properties_key',''))" "$GATE_JSON")"
  GATE_ENV="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('env_var',''))" "$GATE_JSON")"
  GATE_PREFIXES="$(python3 -c "import json,sys; print(' '.join(json.loads(sys.argv[1]).get('task_prefixes',[])))" "$GATE_JSON")"
  HAS_CRED="no"
  if [ -n "$GATE_KEY" ] && grep -q "^${GATE_KEY//./\\.}=." "$REPO/local.properties" 2>/dev/null; then HAS_CRED="yes"; fi
  if [ -n "$GATE_ENV" ] && [ -n "${!GATE_ENV:-}" ]; then HAS_CRED="yes"; fi
  if [ "$HAS_CRED" = "no" ]; then
    KEPT=()
    for t in "${TASKS[@]}"; do
      gated="no"
      for p in $GATE_PREFIXES; do [[ "$t" == "$p"* ]] && gated="yes"; done
      if [ "$gated" = "yes" ]; then SKIPPED+=("$t"); else KEPT+=("$t"); fi
    done
    TASKS=("${KEPT[@]+"${KEPT[@]}"}")
    echo "no credential (${GATE_KEY:-$GATE_ENV}): skipping ${#SKIPPED[@]} tasks" >&2
  fi
fi

if [ ! -x "$REPO/gradlew" ]; then
  echo "ERROR: $REPO/gradlew doesn't exist or isn't executable" >&2
  exit 2
fi

LOCK_DIR="$TOOLS_ROOT/out/.gradle.lock"
worktree_lock_acquire "$LOCK_DIR"
trap 'worktree_lock_release "$LOCK_DIR"' EXIT

RESULTS="$RUN_DIR/tasks.jsonl"; : > "$RESULTS"
TIMES="$RUN_DIR/times.jsonl"; : > "$TIMES"
FAILED=0
for t in "${TASKS[@]+"${TASKS[@]}"}"; do
  log="$RUN_DIR/${t//:/_}.log"
  t0=$SECONDS
  if (cd "$REPO" && ./gradlew "$t" -q -Dkotlin.daemon.jvm.options=-Xmx6g) > "$log" 2>&1; then code=0; else code=$?; FAILED=1; fi
  echo "-- $t: exit $code ($((SECONDS - t0))s)" >&2
  python3 -c "import json,sys; print(json.dumps({'task': sys.argv[1], 'exit': int(sys.argv[2]), 'log_path': sys.argv[3]}))" \
    "$t" "$code" "out/verify-sectors/$REPO_SHA$DIRTY_SUFFIX/$RUN_ID/${t//:/_}.log" >> "$RESULTS"
  python3 -c "import json,sys; print(json.dumps({'task': sys.argv[1], 'seconds': int(sys.argv[2])}))" "$t" "$((SECONDS - t0))" >> "$TIMES"
done

python3 - "$TOOLS_ROOT" "$REPO" "$RUN_DIR" "$FAILED" "${SKIPPED[@]+"${SKIPPED[@]}"}" <<'PY'
import json, sys
from pathlib import Path
tools_root, repo, run_dir, failed = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), sys.argv[4] == "1"
skipped = sys.argv[5:]
sys.path.insert(0, str(tools_root))
from lib import baseline, toolenv
selection = json.loads((run_dir / "selection.json").read_text(encoding="utf-8"))
tasks = [json.loads(l) for l in (run_dir / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
times = [json.loads(l) for l in (run_dir / "times.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
payload = baseline.base_envelope(tools_root, baseline.git_head_sha(repo), toolenv.tool_versions(tools_root), baseline.is_repo_dirty(repo))
payload.update({"selection": {k: selection[k] for k in ("tasks", "sectors_hit", "changed_files", "full_required", "full_required_reasons", "unmapped_files")},
                "tasks": tasks, "skipped_no_credential": sorted(skipped), "verdict": "FAIL" if failed else "PASS"})
baseline.write_json(run_dir / "summary.json", payload)
import datetime, platform
(run_dir / "run-meta.json").write_text(json.dumps({"finished_at": datetime.datetime.now().isoformat(timespec="seconds"), "host": platform.node(), "seconds_by_task": times}, indent=2) + "\n", encoding="utf-8")
PY
echo "summary: $RUN_DIR/summary.json" >&2
[ "$FAILED" = "1" ] && exit 1
exit 0
