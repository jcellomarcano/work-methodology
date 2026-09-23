#!/usr/bin/env bash
# Installs the kit into a repo for pi (the @earendil-works/pi-coding-agent
# fork). Same source of truth as Claude Code: 01-roles/agents/, 02-skills/,
# 03-tools/. What changes is the shape, because pi reads agents, skills, MCP
# and extensions from different places and has no hook system.
#
#   bin/install-pi.sh <repo> [--tools <dir>]
#
# --tools <dir>  tools root the extension and the server will use in that repo
#                (an instance synced with bin/sync-instance.sh); defaults to
#                this kit.
#
# Writes only inside <repo>: .pi/agents, .pi/skills, .pi/extensions,
# .pi/mcp.json and .mcp.json. It never writes to ~/.pi/agent/, so nothing
# gentle-ai manages there can be touched.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <repo> [--tools <dir>]" >&2
  exit 2
fi

REPO="$(cd "$1" && pwd)"; shift
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
KIT_ROOT="$(cd "$TOOLS_ROOT/.." && pwd)"
TOOLS_DIR="$TOOLS_ROOT"
while [ $# -gt 0 ]; do
  case "$1" in
    --tools) TOOLS_DIR="$(cd "$2" && pwd)"; shift 2;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

AGENTS_SRC="$KIT_ROOT/01-roles/agents"
SKILLS_SRC="$KIT_ROOT/02-skills"
AGENTS_DST="$REPO/.pi/agents"
SKILLS_DST="$REPO/.pi/skills"
EXT_DST="$REPO/.pi/extensions"
PI_MCP="$REPO/.pi/mcp.json"
MCP_JSON="$REPO/.mcp.json"
EXCLUDE="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo "$REPO/.git")/info/exclude"

# One skill list, kept in install-claude.sh so the two runtimes cannot drift.
SKILLS=()
while IFS= read -r line; do
  SKILLS+=("$line")
done < <(awk '/^SKILLS=\(/{f=1;next} f&&/^\)/{exit} f{gsub(/[ \t]/,"");if($0!="")print}' "$SCRIPT_DIR/install-claude.sh")
if [ "${#SKILLS[@]}" -eq 0 ]; then
  echo "could not read the skill list from install-claude.sh" >&2
  exit 1
fi

mkdir -p "$AGENTS_DST" "$SKILLS_DST" "$EXT_DST"

copied=0
skipped=0

copy_one() {
  local src="$1" dst="$2"
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    echo "  = $dst"
    skipped=$((skipped + 1))
  else
    if [ -f "$dst" ]; then echo "  ~ $dst (updated)"; else echo "  + $dst (new)"; fi
    cp "$src" "$dst"
    copied=$((copied + 1))
  fi
}

RENDER_TMP="$(mktemp -d)"
trap 'rm -rf "$RENDER_TMP"' EXIT

echo "== generic-* agents -> $AGENTS_DST =="
shopt -s nullglob
for f in "$AGENTS_SRC"/generic-*.md; do
  out="$RENDER_TMP/$(basename "$f")"
  python3 "$TOOLS_ROOT/lib/render_agents.py" "$f" --target pi --tools-default "$TOOLS_DIR" --out "$out"
  copy_one "$out" "$AGENTS_DST/$(basename "$f")"
done
shopt -u nullglob

echo "== skills -> $SKILLS_DST =="
for skill in "${SKILLS[@]}"; do
  src_dir="$SKILLS_SRC/$skill"
  if [ ! -d "$src_dir" ]; then
    echo "  ! $src_dir missing in the kit, skipping" >&2
    continue
  fi
  dst_dir="$SKILLS_DST/$skill"
  mkdir -p "$dst_dir"
  for f in "$src_dir"/*; do
    copy_one "$f" "$dst_dir/$(basename "$f")"
  done
done

echo "== metodo MCP server -> $MCP_JSON =="
python3 "$TOOLS_ROOT/lib/mcp_config.py" "$MCP_JSON" --tools-root-expr "$TOOLS_DIR" --repo-expr "$REPO"

echo "== pi override -> $PI_MCP =="
# Every kit skill names its tools as mcp__metodo__<tool>. The adapter's default
# prefix would register them as metodo_<tool>, so this override is what makes
# the skill bodies true on pi.
python3 - "$PI_MCP" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
servers = data.get("mcpServers") or {}
entry = dict(servers.get("metodo") or {})
before = dict(entry)
entry["toolPrefix"] = "mcp"
servers["metodo"] = entry
data["mcpServers"] = servers
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("  = toolPrefix mcp already set" if before == entry else "  + toolPrefix mcp")
PY

echo "== guards extension -> $EXT_DST/metodo-hooks.ts =="
sed -e "s|__TOOLS_DEFAULT__|$TOOLS_DIR|g" -e "s|__REPO_DEFAULT__|$REPO|g" \
  "$TOOLS_ROOT/hooks/pi/metodo-hooks.ts" > "$RENDER_TMP/metodo-hooks.ts"
copy_one "$RENDER_TMP/metodo-hooks.ts" "$EXT_DST/metodo-hooks.ts"

echo "== excluded from commits ($EXCLUDE) =="
if [ -d "$(dirname "$(dirname "$EXCLUDE")")" ]; then
  mkdir -p "$(dirname "$EXCLUDE")"
  for entry in ".mcp.json" ".pi/agents" ".pi/skills" ".pi/extensions/metodo-hooks.ts" ".pi/mcp.json"; do
    if grep -qxF "$entry" "$EXCLUDE" 2>/dev/null; then
      echo "  = $entry"
    else
      echo "$entry" >> "$EXCLUDE"
      echo "  + $entry"
    fi
  done
fi

echo "== server smoke test =="
if [ -f "$TOOLS_DIR/mcp/server.py" ]; then
  METODO_REPO="$REPO" python3 "$TOOLS_DIR/mcp/server.py" --selftest --tools-root "$TOOLS_DIR"
else
  echo "  ! $TOOLS_DIR has no mcp/server.py: run bin/sync-instance.sh $TOOLS_DIR first" >&2
fi

echo
echo "summary: $copied copied/updated, $skipped unchanged; tools root: $TOOLS_DIR"
echo "untouched: ~/.pi/agent/ and everything gentle-ai manages there"
echo "note: pi loads .pi/extensions only after the project is trusted (/trust, or defaultProjectTrust)"
