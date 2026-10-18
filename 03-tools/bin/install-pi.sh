#!/usr/bin/env bash
# Installs the kit into a repo for pi (the @earendil-works/pi-coding-agent
# fork). Same source of truth as Claude Code: 01-roles/agents/, 02-skills/,
# 03-tools/. What changes is the shape, because pi reads agents, skills, MCP
# and extensions from different places and has no hook system.
#
#   bin/install-pi.sh <repo> [--tools <dir>] [--uninstall]
#
# --tools <dir>  tools root the extension and the server will use in that repo
#                (an instance synced with bin/sync-instance.sh); defaults to
#                this kit.
# --uninstall    removes only what this script installed, and only when it is
#                byte-identical to what it renders for the repo (for --tools,
#                or for the tools root .mcp.json records): .pi/agents/generic-*,
#                the listed .pi/skills files, .pi/extensions/metodo-hooks.ts,
#                the toolPrefix override in .pi/mcp.json, the shared
#                mcpServers.metodo (kept while Claude Code's kit hooks remain),
#                each exclude line once its path is gone, and empty dirs. An
#                agent an older kit installed also counts when this kit is a
#                git checkout (render_agents.py --candidates-dir). A
#                modified kit file is kept as `kept: modified`.
#
# Writes only inside <repo>: .pi/agents, .pi/skills, .pi/extensions,
# .pi/mcp.json and .mcp.json. It never writes to ~/.pi/agent/, so nothing
# gentle-ai manages there can be touched.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <repo> [--tools <dir>] [--uninstall]" >&2
  exit 2
fi

REPO="$(cd "$1" && pwd)"; shift
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
KIT_ROOT="$(cd "$TOOLS_ROOT/.." && pwd)"
TOOLS_DIR="$TOOLS_ROOT"
TOOLS_ARG=""
UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tools) [ $# -ge 2 ] || { echo "--tools needs a value" >&2; exit 2; }
             TOOLS_ARG="$2"; shift 2;;
    --uninstall) UNINSTALL=1; shift;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
if [ -n "$TOOLS_ARG" ]; then
  if [ -d "$TOOLS_ARG" ]; then
    TOOLS_DIR="$(cd "$TOOLS_ARG" && pwd)"
  elif [ "$UNINSTALL" = "1" ]; then
    # uninstalling after the instance is gone: the path is only used to render
    case "$TOOLS_ARG" in /*) TOOLS_DIR="$TOOLS_ARG";; *) TOOLS_DIR="$PWD/$TOOLS_ARG";; esac
  else
    echo "tools root is not a directory: $TOOLS_ARG" >&2; exit 2
  fi
fi

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

EXCLUDE_ENTRIES=(".mcp.json" ".pi/agents" ".pi/skills" ".pi/extensions/metodo-hooks.ts" ".pi/mcp.json")

if [ "$UNINSTALL" = "1" ]; then
  echo "== removing the kit's additions from $REPO (pi) =="
  RENDER_TMP="$(mktemp -d)"
  trap 'rm -rf "$RENDER_TMP"' EXIT
  n_removed=0; n_kept=0; n_missing=0
  item() {
    echo "  $1 $2 ($3)"
    case "$1" in -) n_removed=$((n_removed + 1));; !) n_kept=$((n_kept + 1));; .) n_missing=$((n_missing + 1));; esac
  }
  rel() { local p="$1"; echo "${p#"$REPO"/}"; }
  # Deletes <dst> only when it is byte-identical to one of the rendered candidates.
  remove_if_rendered() {
    local dst="$1" c; shift
    if [ ! -e "$dst" ] && [ ! -L "$dst" ]; then item . "$(rel "$dst")" "not found"; return 0; fi
    if [ -f "$dst" ] && [ ! -L "$dst" ]; then
      for c in "$@"; do
        if cmp -s "$c" "$dst"; then rm -f "$dst"; item - "$(rel "$dst")" "removed"; return 0; fi
      done
    fi
    item ! "$(rel "$dst")" "kept: modified"
  }
  rmdir_if_empty() {
    if [ -d "$1" ] && [ ! -L "$1" ] && rmdir "$1" 2>/dev/null; then item - "$(rel "$1")/" "removed"; fi
    return 0
  }

  # What install renders depends on the tools root: the one given (or the
  # default) and the one .mcp.json recorded at install time both count.
  ROOTS=("$TOOLS_DIR")
  recorded_tools() {
    python3 - "$MCP_JSON" <<'PY' 2>/dev/null || true
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(((data.get("mcpServers") or {}).get("metodo") or {}).get("env", {}).get("METODO_TOOLS") or "")
except Exception:
    print("")
PY
  }
  recorded="$(recorded_tools)"
  if [ -n "$recorded" ] && [ "$recorded" != "$TOOLS_DIR" ]; then ROOTS+=("$recorded"); fi

  shopt -s nullglob
  # An agent counts as the kit's when it matches anything an install of this
  # kit may have written: today's render, today's render without the subagent
  # core (the pre-core format), and, in a git checkout, each committed version
  # rendered by the renderer, contract and core committed with it
  # (render_agents.py --candidates-dir). Without git history only the first two.
  if ! git -C "$KIT_ROOT" rev-parse --show-prefix >/dev/null 2>&1; then
    echo "  note: $KIT_ROOT is not a git checkout: agents an older kit installed may be kept as modified"
  fi
  agents=("$AGENTS_SRC"/generic-*.md)
  i=0
  for root in "${ROOTS[@]}"; do
    if [ "${#agents[@]}" -gt 0 ]; then
      python3 "$TOOLS_ROOT/lib/render_agents.py" "${agents[@]}" --target pi --tools-default "$root" \
        --core-source "$KIT_ROOT/CONTEXT-PACK.md" --kit-root "$KIT_ROOT" --candidates-dir "$RENDER_TMP/a$i" >/dev/null
    fi
    i=$((i + 1))
  done
  for f in ${agents[@]+"${agents[@]}"}; do
    cands=(); i=0
    for root in "${ROOTS[@]}"; do cands+=("$RENDER_TMP/a$i/$(basename "$f")"/*); i=$((i + 1)); done
    remove_if_rendered "$AGENTS_DST/$(basename "$f")" ${cands[@]+"${cands[@]}"}
  done
  for skill in "${SKILLS[@]}"; do
    src_dir="$SKILLS_SRC/$skill"; dst_dir="$SKILLS_DST/$skill"
    [ -d "$src_dir" ] || continue
    if [ ! -d "$dst_dir" ]; then item . "$(rel "$dst_dir")/" "not found"; continue; fi
    for f in "$src_dir"/*; do
      dst="$dst_dir/$(basename "$f")"
      { [ -e "$dst" ] || [ -L "$dst" ]; } || continue
      cands=(); i=0
      for root in "${ROOTS[@]}"; do
        if grep -q "__TOOLS_DEFAULT__" "$f" 2>/dev/null; then
          mkdir -p "$RENDER_TMP/c$i/skills/$skill"
          sed "s|__TOOLS_DEFAULT__|$root|g" "$f" > "$RENDER_TMP/c$i/skills/$skill/$(basename "$f")"
          cands+=("$RENDER_TMP/c$i/skills/$skill/$(basename "$f")")
        else
          cands+=("$f")
        fi
        i=$((i + 1))
      done
      remove_if_rendered "$dst" "${cands[@]}"
    done
    rmdir_if_empty "$dst_dir"
  done
  shopt -u nullglob
  rmdir_if_empty "$AGENTS_DST"
  rmdir_if_empty "$SKILLS_DST"

  cands=(); i=0
  for root in "${ROOTS[@]}"; do
    mkdir -p "$RENDER_TMP/c$i"
    sed -e "s|__TOOLS_DEFAULT__|$root|g" -e "s|__REPO_DEFAULT__|$REPO|g" \
      "$TOOLS_ROOT/hooks/pi/metodo-hooks.ts" > "$RENDER_TMP/c$i/metodo-hooks.ts"
    cands+=("$RENDER_TMP/c$i/metodo-hooks.ts"); i=$((i + 1))
  done
  remove_if_rendered "$EXT_DST/metodo-hooks.ts" "${cands[@]}"
  rmdir_if_empty "$EXT_DST"

  out="$(python3 "$TOOLS_ROOT/lib/mcp_config.py" "$PI_MCP" --pi-override --remove)"
  if grep -q '"changed": true' <<<"$out"; then
    item - ".pi/mcp.json#mcpServers.metodo" "removed"
  else
    item . ".pi/mcp.json#mcpServers.metodo" "not found"
  fi
  rmdir_if_empty "$REPO/.pi"

  # .mcp.json's metodo entry is shared with Claude Code: kept while its kit hooks remain.
  if grep -q "metodo-hook" "$REPO/.claude/settings.local.json" 2>/dev/null && grep -q '"metodo"' "$MCP_JSON" 2>/dev/null; then
    item = ".mcp.json#mcpServers.metodo" "kept: shared with claude"
  else
    out="$(python3 "$TOOLS_ROOT/lib/mcp_config.py" "$MCP_JSON" --remove)"
    if grep -q '"changed": true' <<<"$out"; then
      item - ".mcp.json#mcpServers.metodo" "removed"
    else
      item . ".mcp.json#mcpServers.metodo" "not found"
    fi
  fi

  # An exclude line goes only once the path it names is gone.
  if [ -f "$EXCLUDE" ]; then
    for entry in "${EXCLUDE_ENTRIES[@]}"; do
      grep -qxF "$entry" "$EXCLUDE" || continue
      if [ -e "$REPO/$entry" ] || [ -L "$REPO/$entry" ]; then
        item = "info/exclude#$entry" "kept: $entry still exists"
      else
        python3 - "$EXCLUDE" "$entry" <<'PY'
import sys
path, entry = sys.argv[1], sys.argv[2].encode()
lines = open(path, "rb").read().splitlines(keepends=True)
open(path, "wb").write(b"".join(l for l in lines if l.rstrip(b"\r\n") != entry))
PY
        item - "info/exclude#$entry" "removed"
      fi
    done
  fi

  echo
  echo "summary: $n_removed removed, $n_kept kept (modified), $n_missing not found"
  echo "untouched: every file the kit did not install, other keys and servers, ~/.pi/agent/"
  exit 0
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
# render_agents.py appends the subagent core of the kit's CONTEXT-PACK.md to
# every agent, before the contract section and the role marker (last line).
for f in "$AGENTS_SRC"/generic-*.md; do
  out="$RENDER_TMP/$(basename "$f")"
  python3 "$TOOLS_ROOT/lib/render_agents.py" "$f" --target pi --tools-default "$TOOLS_DIR" \
    --core-source "$KIT_ROOT/CONTEXT-PACK.md" --out "$out"
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
    # A skill file that calls a kit script carries __TOOLS_DEFAULT__, rendered
    # to the tools root like the agents; the rest are copied byte for byte.
    if grep -q "__TOOLS_DEFAULT__" "$f" 2>/dev/null; then
      mkdir -p "$RENDER_TMP/skills/$skill"
      sed "s|__TOOLS_DEFAULT__|$TOOLS_DIR|g" "$f" > "$RENDER_TMP/skills/$skill/$(basename "$f")"
      copy_one "$RENDER_TMP/skills/$skill/$(basename "$f")" "$dst_dir/$(basename "$f")"
    else
      copy_one "$f" "$dst_dir/$(basename "$f")"
    fi
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
  for entry in "${EXCLUDE_ENTRIES[@]}"; do
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
