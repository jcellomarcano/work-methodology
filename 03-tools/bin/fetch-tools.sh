#!/usr/bin/env bash
# Downloads the pinned jars/binaries (detekt, PMD, ktlint) to vendor/ and
# records their provenance (URL + sha256) in config/tools.lock.json.
#
# First time: downloads, computes sha256, writes the lock.
# Later times: downloads again to a temp file, compares the sha256 against
# the one already in the lock, and stops hard on a mismatch (the binary
# changed under the same pinned version: that never passes silently).
# If a download fails (no network, release moved, etc.) it's recorded with
# "status": "unavailable" and the rest continues: nothing is ever faked.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENDOR_DIR="$TOOLS_ROOT/vendor"
LOCK_FILE="$TOOLS_ROOT/config/tools.lock.json"

mkdir -p "$VENDOR_DIR"

# name|version|url|dest_filename_in_vendor|post_action(none|unzip|chmod_x)
TOOLS=(
  "detekt|1.23.8|https://github.com/detekt/detekt/releases/download/v1.23.8/detekt-cli-1.23.8-all.jar|detekt-cli-1.23.8-all.jar|none"
  "pmd|7.27.0|https://github.com/pmd/pmd/releases/download/pmd_releases%2F7.27.0/pmd-dist-7.27.0-bin.zip|pmd-dist-7.27.0-bin.zip|unzip"
  "ktlint|1.8.0|https://github.com/pinterest/ktlint/releases/download/1.8.0/ktlint|ktlint|chmod_x"
)

# Loads the already-recorded sha256 values (if the lock exists) as "name<TAB>sha256".
declare -A PRIOR_SHA
if [ -f "$LOCK_FILE" ]; then
  while IFS=$'\t' read -r name sha; do
    [ -n "$name" ] && PRIOR_SHA["$name"]="$sha"
  done < <(python3 -c "
import json
data = json.load(open('$LOCK_FILE'))
for name, entry in data.items():
    print(f\"{name}\t{entry.get('sha256', '')}\")
")
fi

RESULTS_JSONL="$(mktemp)"
trap 'rm -f "$RESULTS_JSONL"' EXIT

for tool_spec in "${TOOLS[@]}"; do
  IFS='|' read -r name version url dest post <<< "$tool_spec"
  dest_path="$VENDOR_DIR/$dest"
  tmp_path="$dest_path.download"
  rel_dest="vendor/$dest"

  echo "== $name $version ==" >&2

  if ! curl -sL --fail --max-time 180 -o "$tmp_path" "$url"; then
    echo "WARNING: could not download $name from $url" >&2
    rm -f "$tmp_path"
    fragment=$(python3 -c "
import json, sys
print(json.dumps({'name': sys.argv[1], 'status': 'unavailable', 'version': sys.argv[2], 'url': sys.argv[3]}))
" "$name" "$version" "$url")
    echo "$fragment" >> "$RESULTS_JSONL"
    continue
  fi

  sha256=$(shasum -a 256 "$tmp_path" | awk '{print $1}')
  prior="${PRIOR_SHA[$name]:-}"
  if [ -n "$prior" ] && [ "$prior" != "$sha256" ]; then
    echo "ERROR: sha256 of $name doesn't match the existing lock" >&2
    echo "  expected (lock): $prior" >&2
    echo "  downloaded now: $sha256" >&2
    rm -f "$tmp_path"
    exit 1
  fi

  mv "$tmp_path" "$dest_path"

  case "$post" in
    unzip)
      unzip -q -o "$dest_path" -d "$VENDOR_DIR"
      ;;
    chmod_x)
      chmod +x "$dest_path"
      ;;
  esac

  fragment=$(python3 -c "
import json, sys
name, status, version, url, sha256, path = sys.argv[1:7]
print(json.dumps({'name': name, 'status': status, 'version': version, 'url': url, 'sha256': sha256, 'path': path}))
" "$name" "ok" "$version" "$url" "$sha256" "$rel_dest")
  echo "$fragment" >> "$RESULTS_JSONL"
done

python3 -c "
import json, sys
sys.path.insert(0, '$TOOLS_ROOT')
from lib import baseline

data = {}
with open('$RESULTS_JSONL', encoding='utf-8') as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        data[obj.pop('name')] = obj
baseline.write_json('$LOCK_FILE', data)
"

echo "tools.lock.json written to $LOCK_FILE" >&2
