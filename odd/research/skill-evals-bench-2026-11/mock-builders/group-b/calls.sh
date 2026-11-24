#!/usr/bin/env bash
# Every call the three scenarios need, through the scratch kit's server; answers kept under $T/answers.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; T="$(cat "$HERE/root.txt")"; TR="$T/kit/03-tools"; A="$T/answers"; mkdir -p "$A"
call() { python3 "$HERE/call.py" "$TR" "$1" "$2" "$3" 2>>"$A/stderr.txt"; }
rid() { python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['run_id'])" "$1"; }
call "$T/bench-repo" benchmark_release '{"ref_a":"v2.3.0","ref_b":"release-2.4"}' > "$A/bench-start-tag.json"
call "$T/bench-repo" job_status "{\"run_id\":\"$(rid "$A/bench-start-tag.json")\",\"wait_seconds\":120}" > "$A/bench-status-tag.json"
call "$T/bench-repo" benchmark_release '{"ref_a":"main","ref_b":"release-2.4"}' > "$A/bench-start-main.json"
call "$T/bench-repo" job_status "{\"run_id\":\"$(rid "$A/bench-start-main.json")\",\"wait_seconds\":120}" > "$A/bench-status-main.json"
call "$T/bench-repo" domain_invariants '{}' > "$A/domain-invariants-head.json"
call "$T/bench-repo" change_card_extract "{\"card_path\":\"$T/card.md\"}" > "$A/card-extract.json"
export METODO_BATTERY_STATE="$T/battery.count"
call "$T/verify-repo" verify_commit '{"range":"v2.3.0..HEAD"}' > "$A/verify-start.json"
call "$T/verify-repo" job_status "{\"run_id\":\"$(rid "$A/verify-start.json")\",\"wait_seconds\":120}" > "$A/verify-status.json"
wc -c "$A"/*.json; cat "$A/stderr.txt"
